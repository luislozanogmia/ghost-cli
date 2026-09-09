"""
Mock In-App Browser browser server for testing InAppBrowserTransport.

Implements the Ghost ↔ In-App Browser protocol over a Unix socket, simulating
In-App Browser's Electron browser with in-memory tab state. No real browser.

Usage:
    server = MockInAppBrowserServer(socket_path, token="test-token")
    server.start()   # runs in a background thread
    ...
    server.stop()
"""

from __future__ import annotations

import json
import os
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Any, Optional


class MockInAppBrowserServer:
    """In-memory mock of In-App Browser's browser endpoint."""

    def __init__(
        self,
        socket_path: str | Path,
        token: Optional[str] = None,
        tcp_port: Optional[int] = None,
    ):
        self.socket_path = Path(socket_path)
        self.token = token
        self.tcp_port = tcp_port
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._server_sock: Optional[socket.socket] = None

        # Simulated browser state
        self._tabs: dict[int, dict[str, Any]] = {
            1: {
                "id": 1,
                "url": "about:blank",
                "title": "New tab",
                "active": True,
                "loading": False,
                "can_go_back": False,
                "can_go_forward": False,
                "history": [],
            }
        }
        self._next_tab_id = 2
        self._active_tab_id = 1

        # Track requests for assertions
        self.requests: list[dict] = []

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Wait for socket to be ready
        for _ in range(50):
            if self.socket_path.exists() or (self._server_sock is not None):
                time.sleep(0.05)
                break
            time.sleep(0.02)

    def stop(self):
        self._stop.set()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3)
        if self.socket_path.exists():
            self.socket_path.unlink(missing_ok=True)

    def _run(self):
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(str(self.socket_path))
        self._server_sock.listen(5)
        self._server_sock.settimeout(0.5)

        while not self._stop.is_set():
            try:
                client, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                self._handle_client(client)
            except Exception:
                pass
            finally:
                client.close()

        self._server_sock.close()
        if self.socket_path.exists():
            self.socket_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Protocol handling
    # ------------------------------------------------------------------

    def _handle_client(self, client: socket.socket):
        client.settimeout(5)

        # Read length prefix
        header = b""
        while len(header) < 4:
            chunk = client.recv(4 - len(header))
            if not chunk:
                return
            header += chunk

        length = struct.unpack(">I", header)[0]
        if length > 16 * 1024 * 1024:
            return

        payload = b""
        while len(payload) < length:
            chunk = client.recv(length - len(payload))
            if not chunk:
                return
            payload += chunk

        request = json.loads(payload.decode("utf-8"))
        self.requests.append(request)

        response = self._dispatch(request)

        resp_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
        client.sendall(struct.pack(">I", len(resp_bytes)) + resp_bytes)

    def _dispatch(self, request: dict) -> dict:
        req_id = request.get("id", "unknown")

        # Auth check
        if self.token and request.get("token") != self.token:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": "AUTH_FAILED", "message": "Invalid or missing token"},
            }

        method = request.get("method", "")
        params = request.get("params", {})

        handler = getattr(self, f"_cmd_{method}", None)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": "UNKNOWN_METHOD", "message": f"Unknown: {method}"},
            }

        try:
            result = handler(params)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": "BROWSER_ERROR", "message": str(exc)},
            }

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _active_tab(self) -> dict:
        return self._tabs[self._active_tab_id]

    def _cmd_status(self, params: dict) -> dict:
        tab = self._active_tab()
        return {
            "connected": True,
            "tabs": len(self._tabs),
            "active_tab_id": self._active_tab_id,
            "active_url": tab["url"],
            "active_title": tab["title"],
        }

    def _cmd_navigate(self, params: dict) -> dict:
        url = params.get("url")
        if not url:
            raise ValueError("url is required")

        tab_id = params.get("tab_id", self._active_tab_id)
        if tab_id not in self._tabs:
            raise ValueError(f"Tab {tab_id} not found")

        tab = self._tabs[tab_id]
        tab["history"].append(tab["url"])
        tab["url"] = url
        tab["title"] = f"Page: {url.split('//')[1].split('/')[0] if '//' in url else url}"
        tab["can_go_back"] = len(tab["history"]) > 0
        tab["loading"] = False

        return {
            "tab_id": tab_id,
            "url": tab["url"],
            "title": tab["title"],
            "loading": False,
        }

    def _cmd_read(self, params: dict) -> dict:
        tab = self._active_tab()
        max_chars = min(params.get("max_chars", 4000), 100_000)

        # Simulate page content
        text = f"Page content for {tab['url']}\n[0] link: Example (https://example.com)"
        if len(text) > max_chars:
            text = text[:max_chars]

        return {
            "url": tab["url"],
            "title": tab["title"],
            "text": text,
            "text_length": len(text),
            "text_truncated": len(text) >= max_chars,
        }

    def _cmd_vacuum(self, params: dict) -> dict:
        url = params.get("url")
        if not url:
            raise ValueError("url is required")

        # Navigate first
        self._cmd_navigate({"url": url})
        tab = self._active_tab()

        text = (
            f"[0] link: Home ({url})\n"
            f"[1] button: Sign In\n"
            f"[2] input(text): Search\n"
            f"[3] link: About (/about)\n"
            f"[4] link: Contact (/contact)"
        )

        return {
            "tab_id": self._active_tab_id,
            "url": tab["url"],
            "title": tab["title"],
            "text": text,
            "element_count": 5,
        }

    def _cmd_click(self, params: dict) -> dict:
        choice = params.get("choice")
        selector = params.get("selector")
        if choice is None and not selector:
            raise ValueError("Provide choice or selector")

        return {
            "clicked": True,
            "tag": "a" if choice == 0 else "button",
            "text": f"Element {choice or selector}",
        }

    def _cmd_fill(self, params: dict) -> dict:
        value = params.get("value")
        if value is None:
            raise ValueError("value is required")

        return {
            "filled": True,
            "tag": "input",
            "value": value,
        }

    def _cmd_key(self, params: dict) -> dict:
        key = params.get("key")
        text = params.get("text")
        if not key and not text:
            raise ValueError("Provide key or text")

        if text:
            return {"typed": text}
        return {"key": key, "pressed": True}

    def _cmd_tab_list(self, params: dict) -> dict:
        return {
            "tabs": [
                {
                    "id": t["id"],
                    "url": t["url"],
                    "title": t["title"],
                    "active": t["id"] == self._active_tab_id,
                }
                for t in self._tabs.values()
            ]
        }

    def _cmd_tab_open(self, params: dict) -> dict:
        url = params.get("url", "about:blank")
        tab_id = self._next_tab_id
        self._next_tab_id += 1

        self._tabs[tab_id] = {
            "id": tab_id,
            "url": url,
            "title": f"Page: {url}" if url != "about:blank" else "New tab",
            "active": False,
            "loading": False,
            "can_go_back": False,
            "can_go_forward": False,
            "history": [],
        }
        self._active_tab_id = tab_id
        self._tabs[tab_id]["active"] = True

        return {"tab_id": tab_id, "url": url, "title": self._tabs[tab_id]["title"]}

    def _cmd_tab_switch(self, params: dict) -> dict:
        tab_id = params.get("tab_id")
        if tab_id not in self._tabs:
            raise ValueError(f"Tab {tab_id} not found")

        for t in self._tabs.values():
            t["active"] = False
        self._tabs[tab_id]["active"] = True
        self._active_tab_id = tab_id

        tab = self._tabs[tab_id]
        return {"tab_id": tab_id, "url": tab["url"], "title": tab["title"]}

    def _cmd_tab_close(self, params: dict) -> dict:
        tab_id = params.get("tab_id")
        if tab_id not in self._tabs:
            raise ValueError(f"Tab {tab_id} not found")
        if len(self._tabs) <= 1:
            raise ValueError("Cannot close the last tab")

        del self._tabs[tab_id]
        if self._active_tab_id == tab_id:
            self._active_tab_id = next(iter(self._tabs))
            self._tabs[self._active_tab_id]["active"] = True

        return {"closed": True}

    def _cmd_back(self, params: dict) -> dict:
        tab = self._active_tab()
        if not tab["history"]:
            return {"navigated": False, "reason": "No history"}
        prev = tab["history"].pop()
        tab["url"] = prev
        tab["title"] = f"Page: {prev}"
        return {"navigated": True, "url": prev}

    def _cmd_forward(self, params: dict) -> dict:
        return {"navigated": False, "reason": "Not implemented in mock"}

    def _cmd_reload(self, params: dict) -> dict:
        tab = self._active_tab()
        return {"reloaded": True, "url": tab["url"]}

    def _cmd_stop(self, params: dict) -> dict:
        return {"stopped": True}

    def _cmd_screenshot(self, params: dict) -> dict:
        return {
            "data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==",
            "width": 1280,
            "height": 720,
        }

    def _cmd_scroll(self, params: dict) -> dict:
        return {
            "scrolled": params.get("direction", "down"),
            "amount": params.get("amount", 500),
        }

    def _cmd_wait(self, params: dict) -> dict:
        ms = params.get("ms", 0)
        if ms:
            time.sleep(min(ms / 1000, 2))  # Cap at 2s in tests
        return {"waited": True}
