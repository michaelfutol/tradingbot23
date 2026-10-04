"""OKX normalization/authentication without any exchange account or order."""

import base64
import hashlib
import hmac
import time
import unittest
from unittest.mock import Mock

from bot import config
from bot.modules.okx_bridge import OKXBridge
from bot.modules.candle_data import closed_candles
from tests.support import isolate_data_dir


class TestOKXBridge(unittest.TestCase):
    def setUp(self):
        isolate_data_dir(self)
        self.session = Mock()
        self.bridge = OKXBridge(self.session)
        self.bridge._instruments = {"BTC-USDT-SWAP": {}}
        self.bridge._instrument_ts = time.monotonic()

    def respond(self, data, code="0"):
        response = Mock()
        response.json.return_value = {"code": code, "data": data}
        self.session.get.return_value = response

    def test_fresh_mark_and_invalid_or_stale_mark(self):
        self.respond([{"instId": "BTC-USDT-SWAP", "markPx": "100", "ts": str(int(time.time() * 1000))}])
        self.assertEqual(self.bridge.futures_symbol_ticker(symbol="BTCUSDT")["price"], 100)
        for price, stamp in (("nan", time.time() * 1000), ("100", 0), ("-1", time.time() * 1000)):
            self.respond([{"instId": "BTC-USDT-SWAP", "markPx": price, "ts": stamp}])
            with self.assertRaises(ValueError):
                self.bridge.futures_symbol_ticker(symbol="BTCUSDT")

    def test_completed_candles_are_ordered_and_forming_candle_excluded(self):
        step = 900000
        end = int(time.time() * 1000) // step * step
        rows = [[str(end - i * step), "100", "101", "99", "100", "1", "1", "100", "1" if i else "0"]
                for i in range(4)]
        self.respond(rows)
        candles = self.bridge.futures_klines(symbol="BTCUSDT", interval="15m", limit=4)
        self.assertEqual(len(candles), 3)
        self.assertEqual(len(closed_candles(candles, "15m", 3)), 3)
        self.assertLess(candles[0][0], candles[-1][0])

    def test_only_active_linear_usdt_swap_supported(self):
        self.bridge._instruments = None
        self.respond([{"instId": "BTC-USDT-SWAP", "state": "live", "settleCcy": "USDT", "ctType": "linear"},
                      {"instId": "ETH-USDT-SWAP", "state": "suspend", "settleCcy": "USDT", "ctType": "linear"}])
        self.assertEqual(self.bridge.instrument("BTCUSDT"), "BTC-USDT-SWAP")
        with self.assertRaises(ValueError):
            self.bridge.instrument("ETHUSDT")
        with self.assertRaises(ValueError):
            self.bridge.instrument("BTC-USDT-SWAP?private=true")

    def test_private_verification_is_demo_read_only_with_correct_signature(self):
        config.OKX_API_KEY, config.OKX_API_SECRET, config.OKX_API_PASSPHRASE = "demo-key", "test-secret", "test-pass"
        self.respond([{"acctLv": "2", "posMode": "net_mode"}])
        result = self.bridge.verify_demo_account()
        call = self.session.get.call_args
        self.assertTrue(call.args[0].endswith("/api/v5/account/config"))
        headers = call.kwargs["headers"]
        expected = base64.b64encode(hmac.new(b"test-secret",
            (headers["OK-ACCESS-TIMESTAMP"] + "GET/api/v5/account/config").encode(), hashlib.sha256).digest()).decode()
        self.assertEqual(headers["OK-ACCESS-SIGN"], expected)
        self.assertEqual(headers["x-simulated-trading"], "1")
        self.assertFalse(result["order_execution_enabled"])
        self.session.post.assert_not_called()
        self.assertNotIn("demo-key", str(result))

    def test_bad_payload_or_missing_credentials_fail_closed(self):
        self.respond([], code="51000")
        with self.assertRaises(ValueError):
            self.bridge._get("/api/v5/public/time")
        config.OKX_API_KEY = ""
        with self.assertRaises(ValueError):
            self.bridge.verify_demo_account()
