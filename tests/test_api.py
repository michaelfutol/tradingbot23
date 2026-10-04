"""API access controls and accounting, without market requests or real account data."""

import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from bot import api, config
from bot.modules.futures_trader import FuturesPosition, FuturesPositionStatus, FuturesTrader
from tests.support import isolate_data_dir


class TestPaperAPI(unittest.TestCase):
    def setUp(self):
        isolate_data_dir(self)
        config.TRADING_MODE = "paper"
        config.MONTHLY_CONTRIBUTION_USD = 0
        env = patch.dict(os.environ, {"WEB_USERNAME": "tester",
                                     "WEB_PASSWORD": "test-only-long-password",
                                     "WEB_ENABLE_CYCLES": "false"})
        env.start()
        self.addCleanup(env.stop)
        self.auth = ("tester", "test-only-long-password")
        self.trader = FuturesTrader()
        self.strategy = SimpleNamespace(trader=self.trader, run_cycle=Mock(return_value={"dips_found": 0}))
        self.strategy.get_status = lambda: {
            "portfolio_value": self.trader.get_portfolio_value(),
            "cash_balance": self.trader.cash_balance, "stats": self.trader.get_stats(), "basket": [],
        }
        state = patch.object(api, "_strategy_instance", self.strategy)
        state.start()
        self.addCleanup(state.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def position(self, **overrides):
        values = dict(symbol="BTC", entry_price=100.0, quantity=10.0, margin_used=100.0,
                      notional=1000.0, leverage=10, entry_time=datetime.now(timezone.utc) - timedelta(days=1),
                      tp_price=102.0, sl_price=0.0, liquidation_price=0.0, last_known_price=101.0,
                      fee_rate=0.001, funding_rate_daily=0.0002)
        values.update(overrides)
        return FuturesPosition(**values)

    def test_private_endpoints_require_auth(self):
        for path in ("/api/status", "/api/history", "/api/config"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(self.client.get(path, auth=("tester", "wrong")).status_code, 401)
        self.assertEqual(self.client.post("/api/cron/run_cycle").status_code, 401)
        self.strategy.run_cycle.assert_not_called()

    def test_unconfigured_auth_fails_closed(self):
        with patch.dict(os.environ, {"WEB_PASSWORD": ""}):
            self.assertEqual(self.client.get("/api/config", auth=self.auth).status_code, 503)
            with self.assertRaisesRegex(RuntimeError, "WEB_USERNAME"):
                with TestClient(api.app):
                    pass

    def test_live_config_rejected_before_initialization(self):
        with patch.object(api, "_strategy_instance", None), patch.object(api, "DataFetcher") as fetcher:
            config.TRADING_MODE = "live"
            with self.assertRaisesRegex(ValueError, "Live trading is not implemented"):
                api.get_strategy()
            fetcher.assert_not_called()

    def test_cycles_are_post_only_and_disabled_by_default(self):
        self.assertEqual(self.client.get("/api/cron/run_cycle", auth=self.auth).status_code, 405)
        self.assertEqual(self.client.post("/api/cron/run_cycle", auth=self.auth).status_code, 403)
        self.strategy.run_cycle.assert_not_called()

    def test_enabled_cycle_and_error_redaction(self):
        with patch.dict(os.environ, {"WEB_ENABLE_CYCLES": "true"}):
            response = self.client.post("/api/cron/run_cycle", auth=self.auth)
            self.assertEqual(response.json()["status"], "success")
            self.strategy.run_cycle.side_effect = RuntimeError("private-error-sentinel")
            response = self.client.post("/api/cron/run_cycle", auth=self.auth)
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("private-error-sentinel", response.text)

    def test_overlapping_cycle_is_rejected(self):
        locked, release = threading.Event(), threading.Event()

        def hold_lock():
            with api._state_lock:
                locked.set()
                release.wait(5)

        thread = threading.Thread(target=hold_lock)
        thread.start()
        try:
            self.assertTrue(locked.wait(2))
            with patch.dict(os.environ, {"WEB_ENABLE_CYCLES": "true"}):
                self.assertEqual(self.client.post("/api/cron/run_cycle", auth=self.auth).status_code, 409)
            self.strategy.run_cycle.assert_not_called()
        finally:
            release.set()
            thread.join(5)

    def test_open_pnl_uses_marks_and_snapshot_costs(self):
        now = datetime.now(timezone.utc)
        pos = self.position(entry_time=now - timedelta(days=1))
        config.FUTURES_FEE_PCT = 0.05
        config.FUNDING_RATE_DAILY = 0.05
        data = api._open_position(pos, now)
        self.assertAlmostEqual(data["pnl_usd"], 7.79)
        self.assertAlmostEqual(data["pnl_pct"], 7.79)
        self.assertEqual(data["age_days"], 1.0)
        pos.fee_rate, pos.funding_rate_daily = None, None
        config.FUTURES_FEE_PCT, config.FUNDING_RATE_DAILY = 0.001, 0.0002
        self.assertAlmostEqual(api._open_position(pos, now)["pnl_usd"], 7.79)

    def test_net_equity_does_not_charge_entry_fee_twice(self):
        self.trader.cash_balance = 899.0
        self.trader.positions = [self.position()]
        data = self.client.get("/api/status", auth=self.auth).json()
        self.assertAlmostEqual(data["portfolio_value"], 1009.0)
        self.assertAlmostEqual(data["estimated_net_equity"], 1007.79, places=4)
        self.assertAlmostEqual(data["open_positions"][0]["pnl_pct"], 7.79, places=4)
        self.assertEqual(data["mode"], "paper")

    def test_history_newest_first_and_percentage_is_not_rescaled(self):
        now = datetime.now(timezone.utc)
        older = self.position(status=FuturesPositionStatus.TP_HIT, exit_time=now - timedelta(hours=1),
                              exit_price=102.0, pnl_pct=1.25, pnl_usd=1.25)
        newer = self.position(symbol="ETH", status=FuturesPositionStatus.TP_HIT,
                              exit_time=now, exit_price=102.0, pnl_pct=1.0, pnl_usd=1.0)
        self.trader.positions = [older, newer]
        data = self.client.get("/api/history", auth=self.auth).json()
        self.assertEqual([row["symbol"] for row in data["history"]], ["ETH", "BTC"])
        self.assertEqual(data["history"][1]["pnl_pct"], 1.25)
        self.assertEqual(data["stats"]["total_trades"], 2)

    def test_config_has_no_secrets_or_wildcard_cors(self):
        response = self.client.get("/api/config", auth=self.auth,
                                   headers={"Origin": "https://untrusted.example"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertNotIn("WEB_PASSWORD", response.text)
        self.assertEqual(self.client.get("/docs").status_code, 404)
