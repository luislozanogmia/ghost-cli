import ast
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_VERSION = "0.4.0"


class VersionTests(unittest.TestCase):
    def test_python_package_version(self):
        module = ast.parse((REPO_ROOT / "__init__.py").read_text())
        versions = [
            node.value.value
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
            and isinstance(node.value, ast.Constant)
        ]
        self.assertEqual(versions, [EXPECTED_VERSION])

    def test_chrome_extension_version(self):
        manifest = json.loads((REPO_ROOT / "extension" / "manifest.json").read_text())
        self.assertEqual(manifest["version"], EXPECTED_VERSION)

    def test_chrome_extension_handshake_uses_manifest_version(self):
        source = (REPO_ROOT / "extension" / "background.js").read_text()
        self.assertIn("version: chrome.runtime.getManifest().version", source)

    def test_chrome_extension_authenticates_before_marking_connected(self):
        source = (REPO_ROOT / "extension" / "background.js").read_text()
        auth_send = source.index('type: "auth", token')
        authenticated = source.index('msg.type === "authenticated"')
        connected = source.index("connected = true", authenticated)
        self.assertLess(auth_send, authenticated)
        self.assertLess(authenticated, connected)
        self.assertNotIn("ghost-bridge?", source)

    def test_hermes_plugin_version(self):
        manifest = (REPO_ROOT / "hermes-plugin" / "plugin.yaml").read_text()
        self.assertIn(f"version: {EXPECTED_VERSION}", manifest)


if __name__ == "__main__":
    unittest.main()
