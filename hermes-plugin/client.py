"""Self-contained local clients used by the Hermes Ghost plugin."""

from __future__ import annotations

import json
import os
import socket
import stat
import struct
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


MAX_MESSAGE_BYTES = 16 * 1024 * 1024
GHOST_TO_HERMES = {
    "ghost_status": "status",
    "ghost_tab_list": "tab_list",
    "ghost_tab_open": "tab_open",
    "ghost_tab_switch": "tab_switch",
    "ghost_tab_close": "tab_close",
    "ghost_navigate": "navigate",
    "ghost_vacuum": "vacuum",
    "ghost_read": "read",
    "ghost_click": "click",
    "ghost_fill": "fill",
    "ghost_key": "key",
    "ghost_eval": "eval",
    "ghost_screenshot": "screenshot",
    "ghost_scroll": "scroll",
    "ghost_wait": "wait",
}


class GhostClientError(RuntimeError):
    pass


def _private_token(env_name: str, file_env: str, default_path: Path) -> str:
    token = os.environ.get(env_name, "").strip()
    if token:
        return token
    path = Path(os.environ.get(file_env, default_path)).expanduser()
    if not path.is_file() or path.is_symlink():
        raise GhostClientError(f"Token file is missing or invalid: {path}")
    info = path.stat()
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise GhostClientError(f"Token file is not owned by the current user: {path}")
    if info.st_mode & 0o077:
        raise GhostClientError(f"Token file permissions must be 0600: {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise GhostClientError(f"Token file is empty: {path}")
    return token


class ChromeClient:
    def __init__(self, port: int, timeout: float = 60):
        self.base_url = f"http://127.0.0.1:{port}"
        self.timeout = timeout
        self.token = _private_token(
            "GHOST_BRIDGE_TOKEN",
            "GHOST_BRIDGE_TOKEN_FILE",
            Path.home() / ".ghost" / "bridge.token",
        )

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=headers,
            method="POST" if data is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_MESSAGE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096)
            raise GhostClientError(f"Chrome bridge rejected the request (HTTP {exc.code}): {raw.decode('utf-8', 'replace')}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise GhostClientError(f"Chrome bridge is unavailable: {exc}") from exc
        if len(raw) > MAX_MESSAGE_BYTES:
            raise GhostClientError("Chrome bridge response exceeded the 16 MiB limit")
        return json.loads(raw)

    def status(self) -> dict[str, Any]:
        return self._request("/status")

    def call(self, command: str, args: dict[str, Any]) -> Any:
        response = self._request("/call", {"command": command, "args": args})
        if "error" in response:
            raise GhostClientError(str(response["error"]))
        return response.get("result", response)


class HermesDesktopClient:
    def __init__(self, port: int, timeout: float = 60):
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())) / "ghost"
        self.socket_path = Path(os.environ.get("GHOST_IN_APP_BROWSER_SOCKET", runtime / "in-app-browser.sock"))
        self.port = port
        self.timeout = timeout
        self.token = _private_token(
            "GHOST_IN_APP_BROWSER_TOKEN",
            "GHOST_IN_APP_BROWSER_TOKEN_FILE",
            runtime / "in-app-browser.token",
        )

    def _connect(self) -> socket.socket:
        if self.socket_path.exists():
            info = self.socket_path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_mode & 0o077:
                raise GhostClientError("Hermes Desktop socket must be a private Unix socket")
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise GhostClientError("Hermes Desktop socket is not owned by the current user")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(str(self.socket_path))
            return sock
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(("127.0.0.1", self.port))
        return sock

    def _receive(self, sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(size - len(data))
            if not chunk:
                raise GhostClientError("Hermes Desktop closed the browser connection")
            data.extend(chunk)
        return bytes(data)

    def call(self, command: str, args: dict[str, Any]) -> Any:
        method = GHOST_TO_HERMES.get(command)
        if method is None:
            raise GhostClientError(f"Unsupported Hermes Desktop command: {command}")
        request_id = uuid.uuid4().hex
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": args,
            "token": self.token,
        }, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise GhostClientError("Browser request exceeded the 16 MiB limit")
        try:
            sock = self._connect()
            with sock:
                sock.sendall(struct.pack(">I", len(payload)) + payload)
                length = struct.unpack(">I", self._receive(sock, 4))[0]
                if length > MAX_MESSAGE_BYTES:
                    raise GhostClientError("Hermes Desktop response exceeded the 16 MiB limit")
                response = json.loads(self._receive(sock, length))
        except (OSError, TimeoutError) as exc:
            raise GhostClientError(f"Hermes Desktop browser is unavailable: {exc}") from exc
        if response.get("id") != request_id:
            raise GhostClientError("Hermes Desktop returned a mismatched request id")
        if response.get("error"):
            raise GhostClientError(str(response["error"]))
        return response.get("result", {})

    def status(self) -> dict[str, Any]:
        result = self.call("ghost_status", {})
        return result if isinstance(result, dict) else {"connected": True, "result": result}


class BrowserClient:
    def __init__(self, backend: str = "auto", chrome_port: int = 9378, hermes_port: int = 9400):
        if backend not in {"auto", "chrome", "hermes"}:
            raise GhostClientError("backend must be auto, chrome, or hermes")
        self.backend = backend
        self.chrome_port = chrome_port
        self.hermes_port = hermes_port
        self.active_backend = ""
        self.transport: ChromeClient | HermesDesktopClient | None = None

    def connect(self):
        failures = []
        if self.backend in {"auto", "hermes"}:
            try:
                candidate = HermesDesktopClient(self.hermes_port)
                status = candidate.status()
                self.transport = candidate
                self.active_backend = "hermes"
                return status
            except Exception as exc:
                failures.append(str(exc))
                if self.backend == "hermes":
                    raise GhostClientError(failures[-1]) from exc
        try:
            candidate = ChromeClient(self.chrome_port)
            status = candidate.status()
            if not status.get("connected"):
                raise GhostClientError("Chrome extension is not connected")
            self.transport = candidate
            self.active_backend = "chrome"
            return status
        except Exception as exc:
            failures.append(str(exc))
            raise GhostClientError("No browser connection is available: " + " | ".join(failures)) from exc

    def call(self, command: str, args: dict[str, Any]):
        if command == "ghost_pdf_read" and self.backend == "hermes":
            raise GhostClientError("ghost_pdf_read is available through the Chrome extension only")
        if command == "ghost_pdf_read" and self.backend == "auto":
            self.backend = "chrome"
        if self.transport is None:
            status = self.connect()
        else:
            status = None
        if command == "ghost_status":
            return status if status is not None else self.transport.status()
        return self.transport.call(command, args)
