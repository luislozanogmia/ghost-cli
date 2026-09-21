from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bridge_auth import BridgeAuthError, load_bridge_token
from bridge_server import BridgeServer


TOKEN = "t" * 48


class FakeSocket:
    def __init__(self, token, origin="chrome-extension://unit-test"):
        self.request = type("Request", (), {"headers": {"Origin": origin}})()
        self.remote_address = ("127.0.0.1", 1)
        self.messages = [json.dumps({"type": "auth", "token": token})]
        self.sent = []
        self.closed = None

    async def recv(self):
        return self.messages.pop(0)

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def close(self, code, reason):
        self.closed = (code, reason)

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class BridgeAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = BridgeServer(token=TOKEN)
        app = web.Application()
        app.router.add_get("/status", self.bridge.handle_status)
        app.router.add_post("/call", self.bridge.handle_call)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_http_rejects_missing_and_wrong_tokens(self):
        response = await self.client.get("/status")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/status", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status, 401)

    async def test_http_accepts_valid_token(self):
        response = await self.client.get("/status", headers={"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())["connected"])

    async def test_call_rejects_invalid_argument_and_timeout_shapes(self):
        headers = {"Authorization": f"Bearer {TOKEN}"}
        response = await self.client.post(
            "/call",
            headers=headers,
            json={"command": "ghost_read", "args": [], "timeout": 10},
        )
        self.assertEqual(response.status, 400)
        response = await self.client.post(
            "/call",
            headers=headers,
            json={"command": "ghost_read", "args": {}, "timeout": True},
        )
        self.assertEqual(response.status, 400)

    async def test_websocket_rejects_untrusted_origin(self):
        socket = FakeSocket(TOKEN, origin="https://example.com")
        await self.bridge.ws_handler(socket)
        self.assertEqual(socket.closed[0], 4003)

    async def test_websocket_rejects_wrong_token(self):
        socket = FakeSocket("wrong")
        await self.bridge.ws_handler(socket)
        self.assertEqual(socket.closed[0], 4003)

    async def test_websocket_accepts_extension_with_valid_token(self):
        socket = FakeSocket(TOKEN)
        await self.bridge.ws_handler(socket)
        self.assertEqual(socket.sent[0], {"type": "authenticated"})


class TokenFileTests(unittest.TestCase):
    def test_generated_token_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            with mock.patch.dict(os.environ, {"GHOST_BRIDGE_TOKEN_FILE": str(path)}, clear=False):
                token = load_bridge_token(create=True)
                self.assertGreaterEqual(len(token.encode()), 32)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_rejects_permissive_token_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text(TOKEN)
            path.chmod(0o644)
            with mock.patch.dict(os.environ, {"GHOST_BRIDGE_TOKEN_FILE": str(path)}, clear=False):
                with self.assertRaises(BridgeAuthError):
                    load_bridge_token()
