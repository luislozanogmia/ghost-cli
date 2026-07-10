from __future__ import annotations

import unittest

from ghost_cli import _live_payload


class LiveStatusPayloadTests(unittest.TestCase):
    def test_live_connection_tells_agents_to_reuse(self) -> None:
        payload = _live_payload(
            instance_id="live",
            proxy_health={"connected": True, "pid": 1234},
            instance_status={
                "instance_id": "live",
                "transport": "chrome-transport",
                "browser_connected": True,
                "cdp_url": "live-chrome",
            },
            reused_existing_connection=True,
        )

        self.assertEqual("live", payload["connection"])
        self.assertFalse(payload["should_reconnect"])
        self.assertIn("CONNECTION IS LIVE", payload["message"])
        self.assertIn("Reuse instance 'live'", payload["action"])

    def test_live_broker_without_instance_still_must_not_reconnect(self) -> None:
        payload = _live_payload(
            instance_id="live",
            proxy_health={"connected": True, "pid": 1234},
            instance_status=None,
            reused_existing_connection=True,
        )

        self.assertEqual("live", payload["connection"])
        self.assertFalse(payload["should_reconnect"])
        self.assertFalse(payload["instance_ready"])

    def test_live_broker_with_wrong_instance_transport_still_must_not_reconnect(self) -> None:
        payload = _live_payload(
            instance_id="live",
            proxy_health={"connected": True, "pid": 1234},
            instance_status={
                "instance_id": "live",
                "transport": "playwright",
                "browser_connected": True,
                "cdp_url": "none",
            },
            reused_existing_connection=True,
        )

        self.assertEqual("live", payload["connection"])
        self.assertFalse(payload["should_reconnect"])
        self.assertFalse(payload["instance_ready"])

    def test_disconnected_broker_requests_one_connection(self) -> None:
        payload = _live_payload(
            instance_id="live",
            proxy_health={},
            instance_status=None,
            reused_existing_connection=False,
        )

        self.assertEqual("disconnected", payload["connection"])
        self.assertTrue(payload["should_reconnect"])
        self.assertEqual("./ghost-cli live-connect --instance-id live", payload["action"])


if __name__ == "__main__":
    unittest.main()
