from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.mock_in_app_browser_server import MockInAppBrowserServer


ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "hermes-plugin"


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "ghost_hermes_plugin",
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RecordingContext:
    def __init__(self):
        self.tools = {}

    def get_config(self, _key, default=None):
        return default

    def register_tool(self, name, **kwargs):
        self.tools[name] = kwargs


class HermesPluginTests(unittest.TestCase):
    def test_registers_focused_tool_surface(self):
        context = RecordingContext()
        load_plugin().register(context)
        self.assertIn("ghost_eval", context.tools)
        self.assertNotIn("ghost_" + "save_auth", context.tools)
        self.assertIn("ghost_pdf_read", context.tools)
        self.assertEqual(len(context.tools), 16)

    def test_manifest_matches_registered_tools(self):
        context = RecordingContext()
        load_plugin().register(context)
        manifest = (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")
        for name in context.tools:
            self.assertIn(f"  - {name}\n", manifest)

    def test_status_handler_returns_connection_status_without_browser_command(self):
        module = load_plugin()

        class FakeClient:
            def __init__(self, *_args):
                self.active_backend = "chrome"

            def call(self, name, arguments):
                self.assertions = (name, arguments)
                return {"connected": True}

        module.BrowserClient = FakeClient
        context = RecordingContext()
        module.register(context)
        result = context.tools["ghost_status"]["handler"]({})
        self.assertIn('"connected": true', result)

    def test_self_contained_client_calls_hermes_eval(self):
        module = load_plugin()
        client_module = __import__(module.__name__ + ".client", fromlist=["BrowserClient"])
        with tempfile.TemporaryDirectory() as directory:
            socket_path = Path(directory) / "browser.sock"
            token = "hermes-test-token-0123456789abcdef"
            server = MockInAppBrowserServer(socket_path, token=token)
            server.start()
            try:
                with mock.patch.dict(os.environ, {
                    "GHOST_IN_APP_BROWSER_SOCKET": str(socket_path),
                    "GHOST_IN_APP_BROWSER_TOKEN": token,
                }, clear=False):
                    client = client_module.BrowserClient(backend="hermes", allow_eval=True)
                    result = client.call("ghost_eval", {"script": "() => document.title"})
                self.assertEqual(result["value"], "mock-result")
                self.assertEqual(client.active_backend, "hermes")
            finally:
                server.stop()

    def test_eval_is_disabled_without_explicit_opt_in(self):
        module = load_plugin()
        client_module = __import__(module.__name__ + ".client", fromlist=["BrowserClient"])
        client = client_module.BrowserClient(backend="chrome")
        with self.assertRaisesRegex(client_module.GhostClientError, "disabled"):
            client.call("ghost_eval", {"script": "() => document.cookie"})


class RepositoryBoundaryTests(unittest.TestCase):
    def test_removed_legacy_terms_do_not_reappear(self):
        terms = (
            "play" + "wright",
            "c" + "dp",
            "remote " + "debu" + "gging",
            "chrome" + "-devtools" + "-mcp",
        )
        violations = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".js", ".json", ".md", ".html", ".sh", ".yaml"}:
                continue
            lowered = path.read_text(encoding="utf-8", errors="ignore").lower()
            for term in terms:
                if term in lowered:
                    violations.append(f"{path.relative_to(ROOT)}: {term}")
        self.assertEqual(violations, [])
