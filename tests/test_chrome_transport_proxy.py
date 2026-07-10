from __future__ import annotations

import json
import unittest

from chrome_transport_proxy import GhostChromeProxy


class _Request:
    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


class _Client:
    def __init__(self, *, result: str = "", error: Exception | None = None, healthy: bool = True) -> None:
        self._result = result
        self._error = error
        self.transport_healthy = healthy

    async def call_tool(self, *_args, **_kwargs) -> str:
        if self._error is not None:
            raise self._error
        return self._result


class ChromeTransportProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_file_tool_result_keeps_session(self) -> None:
        proxy = GhostChromeProxy()
        proxy._client = _Client(result="")
        proxy._session_healthy = True

        response = await proxy._handle_call(
            _Request({"name": "take_snapshot", "arguments": {"filePath": "/tmp/snapshot.txt"}})
        )

        self.assertEqual(200, response.status)
        self.assertEqual({"result": "", "error": None}, json.loads(response.text))
        self.assertTrue(proxy._session_healthy)
        self.assertFalse(proxy._session_cycle_event.is_set())

    async def test_tool_error_keeps_healthy_transport(self) -> None:
        proxy = GhostChromeProxy()
        proxy._client = _Client(error=RuntimeError("page changed"), healthy=True)
        proxy._session_healthy = True

        response = await proxy._handle_call(_Request({"name": "take_snapshot", "arguments": {}}))

        self.assertEqual(200, response.status)
        self.assertEqual("page changed", json.loads(response.text)["error"])
        self.assertTrue(proxy._session_healthy)
        self.assertFalse(proxy._session_cycle_event.is_set())

    async def test_tool_error_reconnects_dead_transport(self) -> None:
        proxy = GhostChromeProxy()
        proxy._client = _Client(error=RuntimeError("disconnected"), healthy=False)
        proxy._session_healthy = True

        await proxy._handle_call(_Request({"name": "list_pages", "arguments": {}}))

        self.assertFalse(proxy._session_healthy)
        self.assertTrue(proxy._session_cycle_event.is_set())


if __name__ == "__main__":
    unittest.main()
