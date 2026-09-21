"""Authenticated HTTP client for Ghost's Chrome extension bridge."""

import json
import urllib.request
import urllib.error

from bridge_auth import load_bridge_token


class BridgeTransport:
    """Synchronous HTTP client for the Ghost Bridge server."""

    def __init__(self, port=9378, timeout=60, token=None):
        self.base_url = f"http://127.0.0.1:{port}"
        self.timeout = timeout
        self.token = token or load_bridge_token()
        self._connected = False

    def _headers(self, *, json_body=False):
        headers = {"Authorization": f"Bearer {self.token}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def status(self):
        """Check bridge server and extension status."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/status",
                headers=self._headers(),
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                self._connected = data.get("connected", False)
                return data
        except (urllib.error.URLError, ConnectionError, TimeoutError):
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

        req = urllib.request.Request(
            f"{self.base_url}/call",
            data=payload,
            headers=self._headers(json_body=True),
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=(timeout or self.timeout) + 5) as resp:
                data = json.loads(resp.read())
                if "error" in data:
                    raise BridgeError(data["error"])
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
