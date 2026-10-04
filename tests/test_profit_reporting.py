"""One net P&L estimate across the personal dashboard, Telegram and web API."""

import unittest
from datetime import datetime, timedelta, timezone

from bot import config
from bot.dashboard import Dashboard
from bot.modules.futures_trader import FuturesPosition, FuturesPositionStatus, FuturesTrader
from tests.support import isolate_data_dir


class TestProfitReporting(unittest.TestCase):
    def setUp(self):
        isolate_data_dir(self)
        config.CAPITAL_USD = 1000
        config.MONTHLY_CONTRIBUTION_USD = 0
        self.trader = FuturesTrader()
        self.now = datetime.now(timezone.utc)
        self.pos = FuturesPosition(
            symbol="BTC", entry_price=100.0, quantity=10.0, margin_used=100.0,
            notional=1000.0, leverage=10, entry_time=self.now - timedelta(days=1),
            tp_price=102.0, sl_price=0.0, liquidation_price=0.0,
            last_known_price=101.0, fee_rate=0.001, funding_rate_daily=0.0002,
        )
        self.trader.positions = [self.pos]
        self.trader.cash_balance = 899.0  # Starting cash minus margin and paid entry fee.

    def test_estimate_matches_actual_close_accounting(self):
        before = self.trader.get_equity_breakdown(self.now)
        estimate = self.trader.estimate_position_pnl(self.pos, self.now)
        self.trader._close(self.pos, 101.0, FuturesPositionStatus.TP_HIT, self.now)
        self.assertAlmostEqual(self.pos.pnl_usd, estimate["pnl_usd"])
        self.assertAlmostEqual(self.pos.pnl_pct, estimate["pnl_pct"])
        self.assertAlmostEqual(self.trader.cash_balance, before["estimated_net_equity_usd"])
        after = self.trader.get_equity_breakdown(self.now)
        self.assertAlmostEqual(after["realized_net_pnl_usd"], 7.79)
        self.assertEqual(after["unrealized_net_pnl_usd"], 0.0)

    def test_equity_costs_are_charged_once(self):
        values = self.trader.get_equity_breakdown(self.now)
        self.assertAlmostEqual(values["marked_equity_usd"], 1009.0)
        self.assertAlmostEqual(values["estimated_net_equity_usd"], 1007.79)
        self.assertAlmostEqual(values["unrealized_net_pnl_usd"], 7.79)
        self.assertAlmostEqual(values["estimated_exit_fees_usd"], 1.01)
        self.assertAlmostEqual(values["estimated_funding_usd"], 0.2)

    def test_estimate_uses_original_costs_and_clamps_future_entry_age(self):
        config.FUTURES_FEE_PCT = 0.05
        config.FUNDING_RATE_DAILY = 0.05
        self.assertAlmostEqual(self.trader.estimate_position_pnl(self.pos, self.now)["pnl_usd"], 7.79)
        self.pos.entry_time = self.now + timedelta(hours=1)
        result = self.trader.estimate_position_pnl(self.pos, self.now)
        self.assertEqual(result["age_days"], 0.0)
        self.assertEqual(result["funding_usd"], 0.0)

    def test_legacy_position_cost_fallback(self):
        self.pos.fee_rate = None
        self.pos.funding_rate_daily = None
        config.FUTURES_FEE_PCT = 0.001
        config.FUNDING_RATE_DAILY = 0.0002
        self.assertAlmostEqual(self.trader.estimate_position_pnl(self.pos, self.now)["pnl_usd"], 7.79)

    def test_telegram_does_not_display_stale_open_pnl_field(self):
        self.pos.pnl_pct = 0.0
        dashboard = Dashboard.__new__(Dashboard)
        dashboard.trader = self.trader
        dashboard._paused = True
        dashboard._last_cycle_time = None
        text = dashboard._telegram_futures_snapshot()
        self.assertIn("Net PNL +7.79%", text)
        self.assertIn("Net equity est.", text)
        self.assertIn("Open net est.", text)
