"""Authenticated HTTP client for Ghost's Chrome extension bridge."""

import json
import secrets
import time
import urllib.request
import urllib.error

from bridge_auth import (
    AUTH_NONCE_HEADER,
    AUTH_SIGNATURE_HEADER,
    AUTH_TIMESTAMP_HEADER,
    AUTH_WINDOW_SECONDS,
    RESPONSE_SIGNATURE_HEADER,
    challenge_init_signature,
    load_bridge_token,
    signed_request_headers,
    verify_challenge_signature,
    verify_response_signature,
)


MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class BridgeTransport:
    """Synchronous HTTP client for the Ghost Bridge server."""

    def __init__(self, port=9378, timeout=60, token=None):
        self.base_url = f"http://127.0.0.1:{port}"
        self.timeout = timeout
        self.token = token or load_bridge_token()
        self._connected = False

    @staticmethod
    def _read_bounded(response):
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BridgeError("UNTRUSTED_BRIDGE: response exceeded the 16 MiB limit")
        return raw

    def _challenge(self, timeout):
        client_nonce = secrets.token_hex(16)
        timestamp = str(int(time.time()))
        request = urllib.request.Request(
            self.base_url + "/challenge",
            headers={
                AUTH_TIMESTAMP_HEADER: timestamp,
                AUTH_NONCE_HEADER: client_nonce,
                AUTH_SIGNATURE_HEADER: challenge_init_signature(
                    self.token, client_nonce, timestamp
                ),
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = self._read_bounded(response)
        except urllib.error.HTTPError as exc:
            raise BridgeError(f"UNTRUSTED_BRIDGE: challenge failed with HTTP {exc.code}") from exc
        try:
            data = json.loads(raw)
            instance = data["instance"]
            echoed_nonce = data["client_nonce"]
            challenge = data["challenge"]
            expires = int(data["expires"])
            proof = data["proof"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BridgeError("UNTRUSTED_BRIDGE: invalid authentication challenge") from exc
        now = int(time.time())
        if echoed_nonce != client_nonce or not now <= expires <= now + AUTH_WINDOW_SECONDS:
            raise BridgeError("UNTRUSTED_BRIDGE: stale or mismatched challenge")
        if not verify_challenge_signature(
            self.token, instance, client_nonce, challenge, expires, proof
        ):
            raise BridgeError("UNTRUSTED_BRIDGE: invalid challenge signature")
        return instance, challenge

    def _request(self, method, path, body=b"", *, timeout=5, json_body=False):
        instance, challenge = self._challenge(timeout)
        headers = signed_request_headers(
            self.token,
            method,
            path,
            body,
            instance=instance,
            challenge=challenge,
        )
        if json_body:
            headers["Content-Type"] = "application/json"
        nonce = headers[AUTH_NONCE_HEADER]
        request = urllib.request.Request(
            self.base_url + path,
            data=body if method == "POST" else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = self._read_bounded(response)
                supplied = response.headers.get(RESPONSE_SIGNATURE_HEADER, "")
                if not verify_response_signature(
                    self.token, nonce, response.status, raw, supplied
                ):
                    raise BridgeError("UNTRUSTED_BRIDGE: invalid response signature")
                return response.status, raw
        except urllib.error.HTTPError as exc:
            raw = self._read_bounded(exc)
            supplied = exc.headers.get(RESPONSE_SIGNATURE_HEADER, "")
            if not verify_response_signature(
                self.token, nonce, exc.code, raw, supplied
            ):
                raise BridgeError("UNTRUSTED_BRIDGE: invalid response signature") from exc
            return exc.code, raw

    def status(self):
        """Check bridge server and extension status."""
        try:
            _, raw = self._request("GET", "/status", timeout=5)
            data = json.loads(raw)
            self._connected = data.get("connected", False)
            return data
        except (urllib.error.URLError, ConnectionError, TimeoutError, BridgeError):
            self._connected = False
            return {"connected": False, "error": "Bridge server not running"}

    @property
    def connected(self):
        return self._connected

    def call(self, command, args=None, timeout=None):
        """Send a command to Chrome via the extension bridge."""
        payload = json.dumps({
            "command": command,
            "args": args or {},
            "timeout": timeout or self.timeout,
        }).encode()

        try:
            status, raw = self._request(
                "POST",
                "/call",
                payload,
                timeout=(timeout or self.timeout) + 5,
                json_body=True,
            )
            data = json.loads(raw)
            if "error" in data:
                raise BridgeError(data["error"])
            if status >= 400:
                raise BridgeError(f"HTTP {status}")
            return data.get("result", data)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                err = json.loads(body)
                raise BridgeError(err.get("error", body))
            except json.JSONDecodeError:
                raise BridgeError(f"HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            raise BridgeError(
                f"NO_BRIDGE: Cannot reach bridge server at {self.base_url}. "
                f"Start it with: python3 bridge_server.py"
            )

    def ping(self):
        """Quick connectivity check."""
        try:
            result = self.call("ping", timeout=5)
            return result.get("pong", False)
        except BridgeError:
            return False


class BridgeError(Exception):
    """Error from the bridge server or Chrome extension."""
    pass
