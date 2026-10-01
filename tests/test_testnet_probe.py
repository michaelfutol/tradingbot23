"""Tests for signed Binance futures test-order validation."""

import unittest

from bot.modules.testnet_probe import BinanceTestnetProbe


class FakeClient:
    def __init__(self):
        self.orders = []

    def futures_symbol_ticker(self, symbol):
        return {"symbol": symbol, "price": "100.0"}

    def futures_exchange_info(self):
        return {"symbols": [{
            "symbol": "BTCUSDT",
            "filters": [{
                "filterType": "MARKET_LOT_SIZE",
                "minQty": "0.001",
                "maxQty": "100",
                "stepSize": "0.001",
            }],
        }]}

    def futures_create_test_order(self, **params):
        self.orders.append(params)
        return {"validated": True}

class TestTestnetProbe(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.probe = BinanceTestnetProbe("", "", client=self.client)

    def test_quantity_from_notional_respects_market_step(self):
        quantity = self.probe.quantity_from_notional("BTC", 10.05)
        self.assertEqual(quantity, 0.1)

    def test_validate_market_order_uses_non_matching_test_endpoint(self):
        result = self.probe.validate_market_order(
            "BTC", "BUY", notional_usd=10.05
        )

        self.assertTrue(result["validated"])
        self.assertEqual(len(self.client.orders), 1)
        self.assertEqual(self.client.orders[0]["symbol"], "BTCUSDT")
        self.assertEqual(self.client.orders[0]["side"], "BUY")
        self.assertEqual(self.client.orders[0]["type"], "MARKET")
        self.assertEqual(self.client.orders[0]["quantity"], 0.1)

    def test_invalid_side_is_rejected_before_api_call(self):
        with self.assertRaises(ValueError):
            self.probe.validate_market_order("BTC", "HOLD", quantity=0.1)
        self.assertEqual(self.client.orders, [])


if __name__ == "__main__":
    unittest.main()
