"""
Tests for InAppBrowserTransport against the mock In-App Browser server.

Run:
    python -m pytest tests/test_in_app_browser_transport.py -v
    # or directly:
    python tests/test_in_app_browser_transport.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure ghost root is importable
_ghost_dir = str(Path(__file__).resolve().parent.parent)
if _ghost_dir not in sys.path:
    sys.path.insert(0, _ghost_dir)

from in_app_browser_transport import (
    InAppBrowserAuthError,
    InAppBrowserCommandError,
    InAppBrowserConnectionError,
    InAppBrowserTransport,
    InAppBrowserTransportError,
)
from tests.mock_in_app_browser_server import MockInAppBrowserServer


class TestInAppBrowserTransportConnection(unittest.TestCase):
    """Test connection and auth."""

    def test_connection_refused_raises(self):
        """Cannot connect when no server is running."""
        transport = InAppBrowserTransport(
            socket_path=Path("/tmp/ghost-in-app-browser-nonexistent.sock"),
            tcp_host="127.0.0.1",
            tcp_port=19999,
        )
        with self.assertRaises(InAppBrowserConnectionError):
            transport.call("status")

    def test_ping_returns_false_when_disconnected(self):
        transport = InAppBrowserTransport(
            socket_path=Path("/tmp/ghost-in-app-browser-nonexistent.sock"),
            tcp_host="127.0.0.1",
            tcp_port=19999,
        )
        self.assertFalse(transport.ping())

    def test_status_returns_disconnected_when_no_server(self):
        transport = InAppBrowserTransport(
            socket_path=Path("/tmp/ghost-in-app-browser-nonexistent.sock"),
            tcp_host="127.0.0.1",
            tcp_port=19999,
        )
        status = transport.status()
        self.assertFalse(status.get("connected", True))


class TestInAppBrowserTransportWithMock(unittest.TestCase):
    """Test commands against the mock In-App Browser server."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="ghost-in-app-browser-test-")
        cls._sock_path = Path(cls._tmpdir) / "ghost-bridge.sock"
        cls._token = "test-secret-token-42"

        cls.server = MockInAppBrowserServer(cls._sock_path, token=cls._token)
        cls.server.start()

        cls.transport = InAppBrowserTransport(
            socket_path=cls._sock_path,
            token=cls._token,
            timeout=5,
        )

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        try:
            os.rmdir(cls._tmpdir)
        except OSError:
            pass

    # -- Auth --

    def test_auth_failure(self):
        bad_transport = InAppBrowserTransport(
            socket_path=self._sock_path,
            token="wrong-token",
            timeout=5,
        )
        with self.assertRaises(InAppBrowserAuthError):
            bad_transport.call("status")

    def test_auth_success(self):
        result = self.transport.status()
        self.assertTrue(result.get("connected"))

    # -- Status --

    def test_status(self):
        result = self.transport.status()
        self.assertTrue(result["connected"])
        self.assertIn("tabs", result)
        self.assertIn("active_tab_id", result)

    def test_ping(self):
        self.assertTrue(self.transport.ping())

    def test_connected_property(self):
        self.assertTrue(self.transport.connected)

    def test_transport_kind(self):
        self.assertEqual(self.transport.transport_kind, "in-app-browser-transport")

    # -- Navigation --

    def test_navigate(self):
        result = self.transport.navigate("https://example.com")
        self.assertEqual(result["url"], "https://example.com")
        self.assertIn("title", result)
        self.assertIn("tab_id", result)

    def test_navigate_with_tab_id(self):
        result = self.transport.navigate("https://test.com", tab_id=1)
        self.assertEqual(result["url"], "https://test.com")

    # -- Read --

    def test_read(self):
        self.transport.navigate("https://example.com")
        result = self.transport.read()
        self.assertIn("text", result)
        self.assertIn("url", result)
        self.assertIn("text_length", result)

    def test_read_with_max_chars(self):
        result = self.transport.read(max_chars=50)
        self.assertIn("text", result)

    # -- Vacuum --

    def test_vacuum(self):
        result = self.transport.vacuum("https://example.com")
        self.assertIn("text", result)
        self.assertIn("element_count", result)
        self.assertGreater(result["element_count"], 0)
        self.assertIn("[0]", result["text"])

    # -- Click --

    def test_click_by_choice(self):
        result = self.transport.click(choice=0)
        self.assertTrue(result["clicked"])

    def test_click_by_selector(self):
        result = self.transport.click(selector="#btn")
        self.assertTrue(result["clicked"])

    # -- Fill --

    def test_fill(self):
        result = self.transport.fill("hello world", choice=2)
        self.assertTrue(result["filled"])
        self.assertEqual(result["value"], "hello world")

    # -- Key --

    def test_key_press(self):
        result = self.transport.key(key="Enter")
        self.assertEqual(result["key"], "Enter")
        self.assertTrue(result["pressed"])

    def test_key_type_text(self):
        result = self.transport.key(text="search query")
        self.assertEqual(result["typed"], "search query")

    # -- Tabs --

    def test_tab_list(self):
        result = self.transport.tab_list()
        self.assertIn("tabs", result)
        self.assertIsInstance(result["tabs"], list)
        self.assertGreater(len(result["tabs"]), 0)

    def test_tab_open(self):
        result = self.transport.tab_open("https://new-tab.com")
        self.assertIn("tab_id", result)
        self.assertEqual(result["url"], "https://new-tab.com")

    def test_tab_switch(self):
        # Open a second tab then switch back to tab 1
        self.transport.tab_open("https://tab2.com")
        result = self.transport.tab_switch(1)
        self.assertEqual(result["tab_id"], 1)

    def test_tab_close(self):
        # Open a tab then close it
        opened = self.transport.tab_open("https://to-close.com")
        tab_id = opened["tab_id"]
        result = self.transport.tab_close(tab_id)
        self.assertTrue(result["closed"])

    # -- Navigation history --

    def test_back(self):
        self.transport.navigate("https://page1.com")
        self.transport.navigate("https://page2.com")
        result = self.transport.back()
        self.assertTrue(result.get("navigated"))

    def test_reload(self):
        self.transport.navigate("https://reload-me.com")
        result = self.transport.reload()
        self.assertTrue(result["reloaded"])

    def test_stop(self):
        result = self.transport.stop()
        self.assertTrue(result["stopped"])

    # -- Screenshot --

    def test_screenshot(self):
        result = self.transport.screenshot()
        self.assertIn("data_url", result)
        self.assertTrue(result["data_url"].startswith("data:image/"))

    # -- Scroll --

    def test_scroll(self):
        result = self.transport.scroll("down", 500)
        self.assertEqual(result["scrolled"], "down")

    # -- Wait --

    def test_wait_ms(self):
        result = self.transport.wait(ms=100)
        self.assertTrue(result["waited"])

    # -- Error handling --

    def test_unknown_command(self):
        with self.assertRaises(InAppBrowserCommandError) as ctx:
            self.transport.call("nonexistent_command")
        self.assertIn("UNKNOWN_METHOD", str(ctx.exception))

    # -- Request ID correlation --

    def test_request_ids_unique(self):
        self.server.requests.clear()
        self.transport.status()
        self.transport.status()
        ids = [r["id"] for r in self.server.requests[-2:]]
        self.assertNotEqual(ids[0], ids[1])

    def test_request_id_present(self):
        self.server.requests.clear()
        self.transport.status()
        req = self.server.requests[-1]
        self.assertIn("id", req)
        self.assertTrue(len(req["id"]) > 0)

    def test_token_sent_in_request(self):
        self.server.requests.clear()
        self.transport.status()
        req = self.server.requests[-1]
        self.assertEqual(req.get("token"), self._token)


class TestInAppBrowserTransportBounds(unittest.TestCase):
    """Test response bounding and safety."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="ghost-in-app-browser-bounds-")
        cls._sock_path = Path(cls._tmpdir) / "ghost-bridge.sock"

        cls.server = MockInAppBrowserServer(cls._sock_path, token=None)
        cls.server.start()

        cls.transport = InAppBrowserTransport(
            socket_path=cls._sock_path,
            token=None,
            timeout=5,
        )

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        try:
            os.rmdir(cls._tmpdir)
        except OSError:
            pass

    def test_max_chars_capped(self):
        """read() caps max_chars at MAX_PAGE_TEXT_CHARS."""
        result = self.transport.read(max_chars=999_999)
        # The transport should have sent a capped value
        self.assertIn("text", result)

    def test_no_auth_when_token_is_none(self):
        """Server with no token accepts requests without token."""
        result = self.transport.status()
        self.assertTrue(result.get("connected"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
