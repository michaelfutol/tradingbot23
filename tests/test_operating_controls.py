"""Capital migration, exposure budgets, fresh exits and one-owner controls."""

import json
import queue
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot import config
from bot.dashboard import Dashboard
from bot.modules.account_lock import AccountLock
from bot.modules.futures_trader import FuturesTrader, FuturesPositionStatus
from tests.support import isolate_data_dir


class TestAccountOverhaul(unittest.TestCase):
    def setUp(self):
        isolate_data_dir(self)
        config.CAPITAL_USD = 1000
        config.FUTURES_EXCHANGE = "binance"
        config.LEVERAGE = 20
        config.FUTURES_MAX_ACCOUNT_LEVERAGE = 3
        config.FUTURES_CASH_RESERVE_PCT = 0.20
        config.RISK_MAX_OPEN_EXPOSURE_USD = 0
        config.FUTURES_USE_SL = False
        config.MAX_HOLD_DAYS = 3
        self.trader = FuturesTrader()

    def test_old_monthly_deposits_do_not_override_total_capital(self):
        config.CAPITAL_USD = 100
        self.trader.sync_starting_capital(100)
        with patch.object(self.trader, "get_current_price", return_value=100):
            pos = self.trader.open_position("BTC", margin_usd=10)
        self.trader._close(pos, 101, FuturesPositionStatus.TP_HIT, datetime.now(timezone.utc))
        self.trader._save_open_positions()
        profit = pos.pnl_usd
        path = config.DATA_DIR / "open_positions.json"
        saved = json.loads(path.read_text())
        saved.pop("capital_model")
        saved["cash_balance"] += 340
        path.write_text(json.dumps(saved))
        audit = '{"total_contributed_usd": 340, "contributions": [{"month": "2026-05", "amount_usd": 340}]}'
        audit_path = config.DATA_DIR / "account_state.json"
        audit_path.write_text(audit)

        restored = FuturesTrader()
        self.assertAlmostEqual(restored.get_contributed_capital(), 100)
        self.assertAlmostEqual(restored.cash_balance, 100 + profit, places=4)
        self.assertEqual(audit_path.read_text(), audit)
        self.assertEqual(len(restored.get_trade_history()), 1)
        self.assertAlmostEqual(restored.sync_starting_capital(100), 0)
        self.assertAlmostEqual(FuturesTrader().cash_balance, 100 + profit, places=4)
        events = (config.DATA_DIR / "event_ledger.csv").read_text()
        self.assertIn("CAPITAL_ADJUSTMENT", events)
        self.assertFalse(hasattr(restored, "apply_monthly_contribution"))

    def test_deposits_and_withdrawals_survive_restart_without_becoming_profit(self):
        self.trader.sync_starting_capital(1200)
        config.CAPITAL_USD = 1200
        restored = FuturesTrader()
        self.assertAlmostEqual(restored.cash_balance, 1200)
        self.assertAlmostEqual(restored.get_contributed_capital(), 1200)
        self.assertEqual(restored.get_stats()["total_net_pnl_usd"], 0)
        restored.sync_starting_capital(800)
        config.CAPITAL_USD = 800
        self.assertAlmostEqual(FuturesTrader().cash_balance, 800)

    def test_nonfinite_capital_rejected(self):
        for value in (float("nan"), float("inf"), 0, -1):
            with self.assertRaises(ValueError):
                self.trader.sync_starting_capital(value)
        self.assertEqual(self.trader.cash_balance, 1000)

    def test_exposure_cap_includes_every_position_and_entry_fee(self):
        with patch.object(self.trader, "get_current_price", return_value=100):
            first = self.trader.open_position("BTC", margin_usd=500)
            second = self.trader.open_position("ETH", margin_usd=500)
        self.assertLessEqual(first.notional, 3000)
        self.assertIsNone(second)
        self.assertGreaterEqual(self.trader.cash_balance, 1000 * 0.20)
        self.assertLessEqual(sum(p.notional for p in self.trader.get_open_positions()),
                             self.trader.get_equity_breakdown()["estimated_net_equity_usd"] * 3 + 0.00001)

    def test_reserve_and_dollar_notional_cap_apply_before_filling(self):
        config.LEVERAGE = 1
        config.RISK_MAX_OPEN_EXPOSURE_USD = 500
        self.trader.leverage = 1
        with patch.object(self.trader, "get_current_price", return_value=100):
            pos = self.trader.open_position("BTC", margin_usd=1000)
        self.assertLessEqual(pos.notional, 500)
        self.assertGreaterEqual(self.trader.cash_balance, 200)

    def test_stale_profitable_or_expired_mark_cannot_close_a_trade(self):
        with patch.object(self.trader, "get_current_price", return_value=100):
            pos = self.trader.open_position("BTC", margin_usd=20)
        pos.last_known_price = pos.tp_price * 1.1
        pos.entry_time -= timedelta(days=10)
        with patch.object(self.trader, "get_current_price", return_value=None):
            self.assertEqual(self.trader.check_positions(), [])
        self.assertEqual(pos.status, FuturesPositionStatus.OPEN)

    def test_corrupt_account_fails_without_overwriting(self):
        path = config.DATA_DIR / "open_positions.json"
        path.write_text("broken-account-evidence")
        with self.assertRaisesRegex(ValueError, "cannot be restored"):
            FuturesTrader()
        self.assertEqual(path.read_text(), "broken-account-evidence")

    def test_mark_and_source_survive_restart(self):
        with patch.object(self.trader, "get_current_price", return_value=100):
            pos = self.trader.open_position("BTC", margin_usd=20)
        with patch.object(self.trader, "get_current_price", return_value=99):
            self.trader.check_positions()
        restored = FuturesTrader().get_open_positions()[0]
        self.assertEqual(restored.last_known_price, 99)
        self.assertIsNotNone(restored.mark_updated_at)
        config.FUTURES_EXCHANGE = "okx"
        with self.assertRaisesRegex(ValueError, "another exchange"):
            FuturesTrader()

    def test_only_one_writer_per_account(self):
        with AccountLock(config.DATA_DIR):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                with AccountLock(config.DATA_DIR):
                    pass
        with AccountLock(config.DATA_DIR):
            pass


class TestDesktopControls(unittest.TestCase):
    def app(self):
        app = Dashboard.__new__(Dashboard)
        app._account_lock = threading.RLock()
        app._paused = True
        app._settings_confirmed = True
        app._one_shot_requested = False
        app._bridge_scan_id = None
        app._force_event = threading.Event()
        app._running = True
        app.pause_btn = Mock()
        app.root = Mock()
        app._record_decision = Mock()
        app.trader = Mock()
        app.trader.check_positions.return_value = []
        app.strategy = Mock()
        app.strategy.run_cycle.return_value = {"positions_opened": 0}
        app._risk_allows_trading = Mock(return_value=(True, []))
        app._bridge_snapshot = Mock(return_value={"mode": "paper"})
        app._bridge = SimpleNamespace(commands=queue.Queue(), complete=Mock(), publish=Mock())
        return app

    def test_pause_continues_exits_not_entries(self):
        app = self.app()
        result = app._run_guarded_cycle()
        app.trader.check_positions.assert_called_once()
        app.strategy.run_cycle.assert_not_called()
        self.assertTrue(result["risk_blocked"])

    def test_lum_one_shot_retains_pause_and_obeys_risk_guard(self):
        app = self.app()
        app._bridge.commands.put({"action": "run-once", "id": "test"})
        app._pump_local_bridge()
        self.assertTrue(app._paused)
        self.assertTrue(app._one_shot_requested)
        app._run_guarded_cycle()
        app.strategy.run_cycle.assert_called_once()
        self.assertFalse(app._one_shot_requested)
        self.assertTrue(app._paused)
        app._risk_allows_trading.return_value = (False, ["kill switch"])
        app._bridge.commands.put({"action": "resume", "id": "blocked"})
        app._pump_local_bridge()
        self.assertTrue(app._paused)
        app._bridge.complete.assert_called_with("blocked", "rejected",
            error="Settings/risk guard blocks entries", reasons=["kill switch"])
