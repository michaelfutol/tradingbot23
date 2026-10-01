"""Tests for automated forward-test readiness grading."""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot import config
from bot.modules.futures_trader import FuturesPositionStatus
from bot.modules.readiness import build_readiness_report


class FakeTrader:
    def __init__(self, trades, capital=100.0):
        self._trades = trades
        self._capital = capital

    def get_trade_history(self):
        return list(self._trades)

    def get_contributed_capital(self):
        return self._capital


def trade(pnl, index, status=None):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index)
    return SimpleNamespace(
        pnl_usd=float(pnl),        status=status or (
            FuturesPositionStatus.TP_HIT if pnl > 0 else FuturesPositionStatus.SL_HIT
        ),
        entry_time=now - timedelta(minutes=30),
        exit_time=now,
    )


class TestReadiness(unittest.TestCase):
    def setUp(self):
        config.READINESS_MIN_TRADES = 4
        config.READINESS_MIN_EXPECTANCY_USD = 0
        config.READINESS_MIN_PROFIT_FACTOR = 1.20
        config.READINESS_MAX_DRAWDOWN_PCT = 10
        config.READINESS_MAX_LOSS_STREAK = 2
        config.READINESS_MAX_LIQUIDATIONS = 0

    def test_profitable_sample_passes_gate(self):
        trades = [trade(3, 1), trade(-1, 2), trade(2, 3), trade(1, 4)]
        report = build_readiness_report(FakeTrader(trades))

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["trades"], 4)
        self.assertGreater(report["metrics"]["profit_factor"], 1.2)
        self.assertGreater(report["metrics"]["expectancy_usd"], 0)
    def test_small_or_unsafe_sample_fails_gate(self):
        config.READINESS_MAX_LOSS_STREAK = 1
        trades = [
            trade(-3, 1),
            trade(-2, 2),
            trade(1, 3, FuturesPositionStatus.LIQUIDATED),
        ]
        report = build_readiness_report(FakeTrader(trades))

        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["sample_size"])
        self.assertFalse(report["checks"]["positive_expectancy"])
        self.assertFalse(report["checks"]["loss_streak"])
        self.assertFalse(report["checks"]["liquidations"])


if __name__ == "__main__":
    unittest.main()