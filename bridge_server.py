"""Ghost Bridge Server for the Chrome extension.

Agents call the authenticated loopback HTTP API, which forwards commands to an
authenticated extension connection and returns bounded JSON results.

Usage:
    python3 bridge_server.py [--port 9377]

The server exposes:
    ws://127.0.0.1:9377/ghost-bridge  — Chrome extension connects here
    http://127.0.0.1:9378/call         — Agents POST commands here (JSON-RPC style)
    http://127.0.0.1:9378/status       — GET connection status
"""

import asyncio
import json
import argparse
import hashlib
import hmac
import secrets
import signal
import sys
import time
from contextlib import suppress
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pdf_reader import (
    DEFAULT_MAX_CHARS,
    MAX_OUTPUT_CHARS,
    MAX_PDF_BYTES,
    PdfReadError,
    extract_pdf,
)
from bridge_auth import (
    AUTH_NONCE_HEADER,
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_INSTANCE_HEADER,
    AUTH_CHALLENGE_HEADER,
    AUTH_WINDOW_SECONDS,
    RESPONSE_SIGNATURE_HEADER,
    BridgeAuthError,
    challenge_init_signature,
    challenge_signature,
    load_bridge_token,
    response_signature,
    token_path,
)
from bridge_auth import _request_message
from ghost_tool_defs import TOOL_NAMES

try:
    import websockets
    from websockets.asyncio.server import serve as ws_serve
except ImportError:
    print("Install websockets: pip install websockets>=14.0")
    sys.exit(1)

try:
    from aiohttp import web
except ImportError:
    print("Install aiohttp: pip install aiohttp")
    sys.exit(1)


MAX_HTTP_BODY_BYTES = 1024 * 1024
WS_NONCE_BYTES = 32
HTTP_COMMANDS = TOOL_NAMES | {"ping"}
MAX_PENDING_CHALLENGES = 1024
MAX_INIT_NONCES = 4096


class BridgeServer:
    def __init__(self, port=9377, token=None, allow_eval=False):
        self.port = port
        self.token = token or load_bridge_token(create=True)
        self.extension_ws = None
        self.pending = {}  # id -> Future
        self.pending_pdf_uploads = {}  # one-time token -> Future[bytes]
        self.connected = False
        self.allow_eval = allow_eval
        self.http_nonces = {}
        self.instance_id = secrets.token_hex(16)
        self.http_challenges = {}
        self.http_init_nonces = {}

    # ------------------------------------------------------------------
    # WebSocket handler — Chrome extension connects here
    # ------------------------------------------------------------------

    @staticmethod
    def _origin(websocket):
        request = getattr(websocket, "request", None)
        headers = getattr(request, "headers", None)
        if headers is None:
            headers = getattr(websocket, "request_headers", {})
        return headers.get("Origin") if headers else None

    async def ws_handler(self, websocket):
        origin = self._origin(websocket)
        if not origin or not origin.startswith("chrome-extension://"):
            await websocket.close(code=4003, reason="unauthorized origin")
            return
        try:
            raw_auth = await asyncio.wait_for(websocket.recv(), timeout=5)
            auth = json.loads(raw_auth)
        except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
            await websocket.close(code=4003, reason="authentication required")
            return

        client_nonce = auth.get("client_nonce", "") if auth.get("type") == "auth_init" else ""
        if (
            not isinstance(client_nonce, str)
            or len(client_nonce) != WS_NONCE_BYTES * 2
            or any(char not in "0123456789abcdef" for char in client_nonce)
        ):
            await websocket.close(code=4003, reason="authentication failed")
            return

        server_nonce = secrets.token_hex(WS_NONCE_BYTES)
        server_message = f"ghost-ws-server-v1:{client_nonce}:{server_nonce}".encode()
        server_proof = hmac.new(self.token.encode(), server_message, hashlib.sha256).hexdigest()
        await websocket.send(json.dumps({
            "type": "auth_challenge",
            "server_nonce": server_nonce,
            "server_proof": server_proof,
        }))
        try:
            raw_response = await asyncio.wait_for(websocket.recv(), timeout=5)
            response = json.loads(raw_response)
        except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
            await websocket.close(code=4003, reason="authentication failed")
            return
        supplied = response.get("client_proof", "") if response.get("type") == "auth_response" else ""
        client_message = f"ghost-ws-client-v1:{client_nonce}:{server_nonce}".encode()
        expected = hmac.new(self.token.encode(), client_message, hashlib.sha256).hexdigest()
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
            await websocket.close(code=4003, reason="authentication failed")
            return

        print("[bridge] Authenticated extension connected")
        previous = self.extension_ws
        if previous is not None and previous is not websocket:
            await previous.close(code=4000, reason="replaced by a newer extension connection")
        self.extension_ws = websocket
        self.connected = True
        await websocket.send(json.dumps({"type": "authenticated"}))

        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # Hello handshake
                if msg.get("type") == "hello":
                    print(f"[bridge] Extension v{msg.get('version', '?')} ready")
                    continue

                # Heartbeat
                if msg.get("type") == "heartbeat":
                    continue

                # Response to a pending command
                msg_id = msg.get("id")
                if msg_id and msg_id in self.pending:
                    self.pending[msg_id].set_result(msg)
                    continue

        except websockets.ConnectionClosed:
            pass
        finally:
            print("[bridge] Extension disconnected")
            if self.extension_ws is websocket:
                self.extension_ws = None
                self.connected = False
                # Fail all pending requests
                for future in self.pending.values():
                    if not future.done():
                        future.set_result({"error": "Extension disconnected"})
                self.pending.clear()

    # ------------------------------------------------------------------
    # Send a command to the extension and wait for response
    # ------------------------------------------------------------------

    async def send_command(self, command, args=None, timeout=60):
        if not self.connected or not self.extension_ws:
            raise Exception("NO_EXTENSION: Chrome extension is not connected. "
                            "Install Ghost Bridge and click Connect.")

        msg_id = secrets.token_hex(8)
        future = asyncio.get_event_loop().create_future()
        self.pending[msg_id] = future

        try:
            await self.extension_ws.send(json.dumps({
                "id": msg_id,
                "command": command,
                "args": args or {},
            }))

            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            raise Exception(f"TIMEOUT: Command '{command}' timed out after {timeout}s")
        finally:
            self.pending.pop(msg_id, None)

    # ------------------------------------------------------------------
    # HTTP API — agents POST commands here
    # ------------------------------------------------------------------

    def _authorized(self, request, body=b""):
        timestamp = request.headers.get(AUTH_TIMESTAMP_HEADER, "")
        nonce = request.headers.get(AUTH_NONCE_HEADER, "")
        supplied = request.headers.get(AUTH_SIGNATURE_HEADER, "")
        instance = request.headers.get(AUTH_INSTANCE_HEADER, "")
        challenge = request.headers.get(AUTH_CHALLENGE_HEADER, "")
        try:
            timestamp_value = int(timestamp)
        except (TypeError, ValueError):
            return False
        now = int(time.time())
        challenge_state = self.http_challenges.get(challenge)
        if challenge_state is None:
            return False
        expires, _client_nonce = challenge_state
        if instance != self.instance_id or expires < now:
            return False
        if abs(now - timestamp_value) > AUTH_WINDOW_SECONDS:
            return False
        if len(nonce) != 32 or any(char not in "0123456789abcdef" for char in nonce):
            return False
        self.http_nonces = {
            value: seen for value, seen in self.http_nonces.items()
            if now - seen <= AUTH_WINDOW_SECONDS
        }
        if nonce in self.http_nonces:
            return False
        expected = hmac.new(
            self.token.encode(),
            _request_message(
                request.method,
                request.path,
                timestamp,
                nonce,
                instance,
                challenge,
                body,
            ),
            hashlib.sha256,
        ).hexdigest()
        if not supplied or not hmac.compare_digest(supplied, expected):
            return False
        self.http_challenges.pop(challenge, None)
        self.http_nonces[nonce] = now
        return True

    async def handle_challenge(self, request):
        now = int(time.time())
        timestamp = request.headers.get(AUTH_TIMESTAMP_HEADER, "")
        client_nonce = request.headers.get(AUTH_NONCE_HEADER, "")
        supplied = request.headers.get(AUTH_SIGNATURE_HEADER, "")
        try:
            timestamp_value = int(timestamp)
        except (TypeError, ValueError):
            return self._reject_unauthorized()
        if (
            abs(now - timestamp_value) > AUTH_WINDOW_SECONDS
            or len(client_nonce) != 32
            or any(char not in "0123456789abcdef" for char in client_nonce)
        ):
            return self._reject_unauthorized()
        expected = challenge_init_signature(self.token, client_nonce, timestamp)
        self.http_init_nonces = {
            value: seen for value, seen in self.http_init_nonces.items()
            if now - seen <= AUTH_WINDOW_SECONDS
        }
        if (
            client_nonce in self.http_init_nonces
            or not supplied
            or not hmac.compare_digest(supplied, expected)
        ):
            return self._reject_unauthorized()
        if len(self.http_init_nonces) >= MAX_INIT_NONCES:
            return web.json_response({"error": "Challenge rate limit reached"}, status=503)
        self.http_init_nonces[client_nonce] = now
        self.http_challenges = {
            value: state for value, state in self.http_challenges.items()
            if state[0] >= now
        }
        if len(self.http_challenges) >= MAX_PENDING_CHALLENGES:
            return web.json_response({"error": "Challenge capacity reached"}, status=503)
        challenge = secrets.token_hex(32)
        expires = now + AUTH_WINDOW_SECONDS
        self.http_challenges[challenge] = (expires, client_nonce)
        return web.json_response({
            "instance": self.instance_id,
            "client_nonce": client_nonce,
            "challenge": challenge,
            "expires": expires,
            "proof": challenge_signature(
                self.token,
                self.instance_id,
                client_nonce,
                challenge,
                expires,
            ),
        })

    def _signed_json_response(self, request, data, status=200):
        body = json.dumps(data, separators=(",", ":")).encode()
        nonce = request.headers.get(AUTH_NONCE_HEADER, "")
        headers = {
            RESPONSE_SIGNATURE_HEADER: response_signature(self.token, nonce, status, body)
        }
        return web.Response(body=body, status=status, content_type="application/json", headers=headers)

    def _reject_unauthorized(self):
        return web.json_response(
            {"error": "UNAUTHORIZED"},
            status=401,
        )

    async def handle_call(self, request):
        if request.content_length is not None and request.content_length > MAX_HTTP_BODY_BYTES:
            return web.json_response({"error": "Request body too large"}, status=413)
        try:
            raw_body = await request.read()
        except Exception:
            return web.json_response({"error": "Invalid request body"}, status=400)
        if len(raw_body) > MAX_HTTP_BODY_BYTES:
            return web.json_response({"error": "Request body too large"}, status=413)
        if not self._authorized(request, raw_body):
            return self._reject_unauthorized()
        try:
            body = json.loads(raw_body)
        except Exception:
            return self._signed_json_response(request, {"error": "Invalid JSON"}, status=400)
        if not isinstance(body, dict):
            return self._signed_json_response(
                request, {"error": "JSON body must be an object"}, status=400
            )

        command = body.get("command")
        args = body.get("args", {})
        timeout = body.get("timeout", 60)

        if not isinstance(command, str) or command not in HTTP_COMMANDS:
            return self._signed_json_response(request, {"error": "Unsupported command"}, status=400)
        if command == "ghost_eval" and not self.allow_eval:
            return self._signed_json_response(
                request,
                {"error": "ghost_eval is disabled; restart with --allow-eval to enable it"},
                status=403,
            )
        if not isinstance(args, dict):
            return self._signed_json_response(request, {"error": "'args' must be an object"}, status=400)
        if isinstance(timeout, bool):
            return self._signed_json_response(request, {"error": "'timeout' must be a number"}, status=400)
        try:
            timeout = max(1, min(float(timeout), 300))
        except (TypeError, ValueError):
            return self._signed_json_response(request, {"error": "'timeout' must be a number"}, status=400)

        try:
            if command == "ghost_pdf_read":
                result = await self.handle_pdf_read(args, timeout)
                return self._signed_json_response(request, {"result": result})
            result = await self.send_command(command, args, timeout)
            if "error" in result:
                return self._signed_json_response(request, {"error": result["error"]}, status=502)
            return self._signed_json_response(request, {"result": result.get("result", result)})
        except Exception as e:
            return self._signed_json_response(request, {"error": str(e)}, status=502)

    async def handle_pdf_upload(self, request):
        """Accept one bounded upload created for a single ghost_pdf_read call."""
        token = request.match_info["token"]
        future = self.pending_pdf_uploads.pop(token, None)
        if future is None or future.done():
            return web.json_response({"error": "INVALID_UPLOAD_TOKEN"}, status=404)
        if request.headers.get("X-Ghost-PDF-Token") != token:
            future.set_exception(PdfReadError("INVALID_UPLOAD_TOKEN", "Upload token mismatch."))
            return web.json_response({"error": "INVALID_UPLOAD_TOKEN"}, status=403)

        try:
            declared_size = request.content_length
            if declared_size is not None and declared_size > MAX_PDF_BYTES:
                raise PdfReadError("PDF_TOO_LARGE", f"PDF exceeds the {MAX_PDF_BYTES} byte limit.")
            chunks = []
            total = 0
            async for chunk in request.content.iter_chunked(256 * 1024):
                total += len(chunk)
                if total > MAX_PDF_BYTES:
                    raise PdfReadError("PDF_TOO_LARGE", f"PDF exceeds the {MAX_PDF_BYTES} byte limit.")
                chunks.append(chunk)
            pdf_bytes = b"".join(chunks)
            if not pdf_bytes.lstrip().startswith(b"%PDF-"):
                raise PdfReadError("NOT_A_PDF", "Downloaded content does not have a PDF signature.")
            future.set_result(pdf_bytes)
            return web.json_response({"accepted": True, "bytes": total})
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            status = 413 if "PDF_TOO_LARGE" in str(exc) else 400
            return web.json_response({"error": str(exc)}, status=status)

    @staticmethod
    def _integer_arg(args, name, default, minimum, maximum):
        value = args.get(name, default)
        if isinstance(value, bool):
            raise PdfReadError("INVALID_INPUT", f"{name} must be an integer.")
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise PdfReadError("INVALID_INPUT", f"{name} must be an integer.") from exc
        if not minimum <= value <= maximum:
            raise PdfReadError(
                "INVALID_INPUT", f"{name} must be between {minimum} and {maximum}."
            )
        return value

    async def handle_pdf_read(self, args, timeout):
        """Fetch through Chrome, receive bytes over loopback, then extract text locally."""
        if not isinstance(args, dict):
            raise PdfReadError("INVALID_INPUT", "args must be an object.")
        mode = args.get("mode", "auto")
        if mode not in {"auto", "text", "ocr"}:
            raise PdfReadError("INVALID_MODE", "mode must be one of: auto, text, ocr.")
        page_start = self._integer_arg(args, "page_start", 1, 1, 300)
        page_end = args.get("page_end")
        if page_end is not None:
            page_end = self._integer_arg(args, "page_end", None, page_start, 300)
        max_chars = self._integer_arg(
            args, "max_chars", DEFAULT_MAX_CHARS, 1, MAX_OUTPUT_CHARS
        )
        try:
            timeout = max(1, min(int(timeout), 300))
        except (TypeError, ValueError):
            timeout = 60

        token = secrets.token_urlsafe(32)
        upload_future = asyncio.get_running_loop().create_future()
        self.pending_pdf_uploads[token] = upload_future
        fetch_args = {
            "tab_id": args.get("tab_id"),
            "upload_url": f"http://127.0.0.1:{self.port + 1}/pdf-upload/{token}",
            "upload_token": token,
            "max_bytes": MAX_PDF_BYTES,
        }

        try:
            response = await self.send_command("ghost_pdf_fetch", fetch_args, timeout)
            if "error" in response:
                raise PdfReadError("PDF_FETCH_FAILED", response["error"])
            fetch_metadata = response.get("result", response)
            pdf_bytes = await asyncio.wait_for(upload_future, timeout=timeout)
            extracted = await asyncio.to_thread(
                extract_pdf,
                pdf_bytes,
                page_start=page_start,
                page_end=page_end,
                mode=mode,
                max_chars=max_chars,
                password=args.get("password"),
            )
            return {
                "url": fetch_metadata.get("url"),
                "title": fetch_metadata.get("title"),
                "mime_type": fetch_metadata.get("content_type") or "application/pdf",
                "bytes": len(pdf_bytes),
                "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                **extracted,
            }
        except asyncio.TimeoutError as exc:
            raise PdfReadError("PDF_FETCH_TIMEOUT", "Timed out receiving PDF bytes from Chrome.") from exc
        finally:
            self.pending_pdf_uploads.pop(token, None)
            if not upload_future.done():
                upload_future.cancel()
            else:
                with suppress(asyncio.CancelledError, Exception):
                    upload_future.exception()

    async def handle_status(self, request):
        if not self._authorized(request):
            return self._reject_unauthorized()
        return self._signed_json_response(request, {
            "connected": self.connected,
            "port": self.port,
            "pending_commands": len(self.pending),
        })

    async def handle_health(self, request):
        return web.json_response({"ok": True, "bridge": "ghost"})

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(self):
        # WebSocket server for the extension
        ws_server = await ws_serve(
            self.ws_handler,
            "127.0.0.1",
            self.port,
            # Serve the WS on /ghost-bridge path
        )

        # HTTP server for agent commands
        app = web.Application(client_max_size=MAX_HTTP_BODY_BYTES)
        app.router.add_get("/challenge", self.handle_challenge)
        app.router.add_post("/call", self.handle_call)
        app.router.add_post("/pdf-upload/{token}", self.handle_pdf_upload)
        app.router.add_get("/status", self.handle_status)
        app.router.add_get("/health", self.handle_health)

        runner = web.AppRunner(app)
        await runner.setup()
        http_site = web.TCPSite(runner, "127.0.0.1", self.port + 1)
        await http_site.start()

        print(f"[bridge] WebSocket server on ws://127.0.0.1:{self.port}/ghost-bridge")
        print(f"[bridge] HTTP API on http://127.0.0.1:{self.port + 1}/call")
        print(f"[bridge] Pair the extension with the token stored at {token_path()}")
        print(f"[bridge] Waiting for Chrome extension...")

        # Wait forever
        stop = asyncio.get_event_loop().create_future()

        def shutdown():
            if not stop.done():
                stop.set_result(None)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                asyncio.get_event_loop().add_signal_handler(sig, shutdown)
            except NotImplementedError:
                signal.signal(sig, lambda *_: shutdown())

        try:
            await stop
        finally:
            ws_server.close()
            await ws_server.wait_closed()
            await runner.cleanup()
            print("\n[bridge] Shut down.")


def main():
    parser = argparse.ArgumentParser(description="Ghost Bridge Server")
    parser.add_argument("--port", type=int, default=9377, help="WebSocket port (HTTP = port+1)")
    parser.add_argument(
        "--allow-eval",
        action="store_true",
        help="Explicitly enable arbitrary page JavaScript through ghost_eval",
    )
    args = parser.parse_args()

    try:
        server = BridgeServer(port=args.port, allow_eval=args.allow_eval)
        asyncio.run(server.run())
    except BridgeAuthError as exc:
        raise SystemExit(f"Bridge authentication error: {exc}") from exc


if __name__ == "__main__":
    main()
