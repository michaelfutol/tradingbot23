"""Loopback bridge boundary checks; no bot, exchange or user account involved."""

import json
import queue
import unittest

import requests

from bot import config
from bot.modules.local_bridge import LocalBridge
from tests.support import isolate_data_dir


class TestLocalBridge(unittest.TestCase):
    def setUp(self):
        isolate_data_dir(self)
        self.bridge = LocalBridge(config.DATA_DIR, 0)
        self.addCleanup(self.bridge.close)
        self.session = requests.Session()
        self.session.trust_env = False
        self.addCleanup(self.session.close)
        self.headers = {"Authorization": "Bearer " + self.bridge.token}
        self.bridge.publish({"mode": "paper", "live_orders_enabled": False, "history": [], "p2p": {"enabled": False}})

    def test_loopback_and_authentication_and_browser_rejection(self):
        self.assertEqual(self.bridge.server.server_address[0], "127.0.0.1")
        self.assertEqual(self.session.get(self.bridge.url + "/status").status_code, 401)
        response = self.session.get(self.bridge.url + "/status", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn(self.bridge.token, response.text)
        for header in ({"Origin": "https://untrusted.example"}, {"Host": "evil.example"}):
            self.assertEqual(self.session.get(self.bridge.url + "/status",
                headers={**self.headers, **header}).status_code, 403)

    def test_commands_are_queued_not_executed_and_have_operation_status(self):
        response = self.session.post(self.bridge.url + "/commands", json={"action": "run-once"}, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        operation = response.json()
        self.assertEqual(operation["state"], "queued")
        self.assertEqual(self.bridge.commands.get_nowait(), operation)
        self.bridge.complete(operation["id"], positions_opened=0)
        result = self.session.get(self.bridge.url + "/operations/" + operation["id"], headers=self.headers).json()
        self.assertEqual(result["state"], "completed")

    def test_destructive_live_or_extra_commands_are_rejected(self):
        for payload in ({"action": "reset"}, {"action": "live"}, {"action": "resume", "code": "x"},
                        {"action": ["pause"]}, [], {}):
            response = self.session.post(self.bridge.url + "/commands", json=payload, headers=self.headers)
            self.assertEqual(response.status_code, 400)
        response = self.session.post(self.bridge.url + "/commands", data="x" * 1025, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertTrue(self.bridge.commands.empty())

    def test_queue_is_bounded_and_close_removes_credentials(self):
        for _ in range(16):
            self.bridge.submit("pause")
        with self.assertRaises(queue.Full):
            self.bridge.submit("pause")
        saved = json.loads(self.bridge.access_file.read_text())
        self.assertEqual(saved["url"], self.bridge.url)
        self.bridge.close()
        self.assertFalse(self.bridge.access_file.exists())
