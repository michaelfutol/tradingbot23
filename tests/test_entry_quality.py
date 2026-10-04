"""Entry quality, data safety and honest performance accounting regressions."""

import math
import csv
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from bot import config
from bot.modules.candle_data import closed_candles
from bot.modules.futures_trader import FuturesTrader, FuturesPositionStatus, analyze_pre_trade_klines
from bot.modules.futures_trader import _append_trade_csv, _history_csv
from bot.modules.strategy import Strategy
from tests.support import isolate_data_dir
from tests.test_futures_trader import _klines_from_closes


class FakeTrader:
    cash_balance = 1000

    def __init__(self):
        self.positions = []
        self.calls = []

    def get_open_positions(self):
        return list(self.positions)

    def pre_trade_analysis(self, symbol):
        self.calls.append(symbol)
        score = 90 if symbol == "BETTER" else 65
        return {"decision": "RUN", "score": score, "reason": "confirmed rebound"}

    def open_position(self, symbol, **kwargs):
        pos = SimpleNamespace(symbol=symbol)
        self.positions.append(pos)
        return pos


class TestEntryQuality(unittest.TestCase):
    def setUp(self):
        isolate_data_dir(self)
        config.PRE_TRADE_ANALYSIS_ENABLED = True
        config.PRE_TRADE_CONFIRMATION_ENABLED = True
        config.FUTURES_REQUIRE_DIP = True
        config.PAPER_SYMBOL_GUARD_ENABLED = False
        config.MAX_OPEN_TRADES = 1
        config.BTC_REGIME_FILTER_PCT = -0.015

    def test_fill_waits_for_dip_by_default(self):
        trader = FakeTrader()
        strategy = Strategy(trader=trader)
        strategy.basket = [{"symbol": "AAA", "cmc_rank": 10}]
        with patch.object(strategy.fetcher, "get_top_coins") as fetch:
            self.assertEqual(strategy.fill_empty_slots(), [])
        fetch.assert_not_called()
        self.assertEqual(trader.calls, [])

    def test_prefers_quality_instead_of_first_or_worst_loser(self):
        trader = FakeTrader()
        strategy = Strategy(trader=trader)
        opened = strategy.execute_signals([
            {"symbol": "WORST", "cmc_rank": 10, "change_24h": -7},
            {"symbol": "BETTER", "cmc_rank": 11, "change_24h": -3},
        ])
        self.assertEqual([p.symbol for p in opened], ["BETTER"])
        self.assertEqual(trader.calls, ["WORST", "BETTER"])

    def test_analysis_is_not_retried_for_same_symbol_in_same_cycle(self):
        trader = FakeTrader()
        strategy = Strategy(trader=trader)
        coin = {"symbol": "AAA", "cmc_rank": 10}
        with patch.object(trader, "pre_trade_analysis", return_value=None) as analyze:
            self.assertFalse(strategy._pre_trade_allows_entry(coin, "dip"))
            self.assertFalse(strategy._pre_trade_allows_entry(coin, "fill"))
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(len(strategy.last_pre_trade_decisions), 1)
        self.assertEqual(strategy.last_pre_trade_decisions[0]["decision"], "WAIT")

    def test_missing_analyzer_blocks_entries(self):
        strategy = Strategy(trader=SimpleNamespace())
        self.assertFalse(strategy._pre_trade_allows_entry({"symbol": "BTC"}, "dip"))

    def test_analysis_exception_blocks_entries(self):
        trader = FakeTrader()
        strategy = Strategy(trader=trader)
        with patch.object(trader, "pre_trade_analysis", side_effect=RuntimeError("network")):
            self.assertFalse(strategy._pre_trade_allows_entry({"symbol": "BTC"}, "dip"))

    def test_inconsistent_analysis_cannot_override_wait(self):
        self.assertFalse(Strategy._analysis_allowed({"allowed": True, "decision": "WAIT"}))

    def test_btc_data_failure_blocks_entries(self):
        for value in (None, math.nan, math.inf):
            strategy = Strategy(trader=SimpleNamespace(get_kline_window_change=lambda *a, **kw: value))
            allowed, reason, change = strategy._market_regime_entry_decision()
            self.assertFalse(allowed)
            self.assertIn("unavailable", reason)
            self.assertIsNone(change)

    def test_missing_btc_getter_blocks_entries(self):
        allowed, _, _ = Strategy(trader=SimpleNamespace())._market_regime_entry_decision()
        self.assertFalse(allowed)

    def test_failed_market_data_keeps_exit_checks_running(self):
        trader = FakeTrader()
        trader.check_positions = lambda: [SimpleNamespace(symbol="OLD")]
        trader.get_stats = lambda: {"total_trades": 1, "win_rate": 0}
        trader.get_portfolio_value = lambda: 1000
        strategy = Strategy(trader=trader)
        with (patch.object(strategy, "should_refresh_basket", return_value=False),
              patch.object(strategy, "_update_crash_mode"),
              patch.object(strategy, "detect_dips") as dips,
              patch.object(strategy, "fill_empty_slots") as fill):
            summary = strategy.run_cycle()
        self.assertEqual(summary["positions_closed"], 1)
        self.assertTrue(summary["market_regime_blocked"])
        dips.assert_not_called()
        fill.assert_not_called()

    def test_no_dip_does_not_refill_after_a_close(self):
        trader = FakeTrader()
        trader.check_positions = lambda: [SimpleNamespace(symbol="OLD")]
        trader.get_kline_window_change = lambda *a, **kw: 0.5
        trader.get_stats = lambda: {"total_trades": 1, "win_rate": 100}
        trader.get_portfolio_value = lambda: 1000
        strategy = Strategy(trader=trader)
        with (patch.object(strategy, "should_refresh_basket", return_value=False),
              patch.object(strategy, "_update_crash_mode"),
              patch.object(strategy, "detect_dips", return_value=[])):
            summary = strategy.run_cycle()
        self.assertEqual(summary["positions_closed"], 1)
        self.assertEqual(summary["positions_opened"], 0)
        self.assertEqual(summary["slots_filled"], 0)

    def test_each_cycle_rechecks_quality(self):
        trader = FakeTrader()
        trader.check_positions = lambda: []
        trader.get_kline_window_change = lambda *a, **kw: 0.5
        trader.get_stats = lambda: {"total_trades": 0, "win_rate": 0}
        trader.get_portfolio_value = lambda: 1000
        strategy = Strategy(trader=trader)
        coin = {"symbol": "BTC", "cmc_rank": 1, "change_24h": -3}
        with (patch.object(strategy, "should_refresh_basket", return_value=False),
              patch.object(strategy, "_update_crash_mode"),
              patch.object(strategy, "detect_dips", return_value=[coin]),
              patch.object(trader, "pre_trade_analysis", return_value=None) as analyze):
            strategy.run_cycle()
            strategy.run_cycle()
        self.assertEqual(analyze.call_count, 2)

    def test_exits_checked_even_if_monthly_universe_refresh_fails(self):
        trader = FakeTrader()
        trader.check_positions = lambda: []
        strategy = Strategy(trader=trader)
        with (patch.object(trader, "check_positions", return_value=[]) as exits,
              patch.object(strategy, "refresh_basket", side_effect=RuntimeError("network"))):
            with self.assertRaises(RuntimeError):
                strategy.run_cycle()
        exits.assert_called_once()

    def test_confirmation_rejects_old_bounce_with_flat_recent_closes(self):
        closes = [100 - i * 0.08 for i in range(70)]
        closes += [94.4, 94.2, 94.0, 94.3, 94.7, 95.1, 95.5, 95.9, 96.2]
        closes += [96.4] * (97 - len(closes))
        analysis = analyze_pre_trade_klines("BTC", _klines_from_closes(closes))
        self.assertFalse(analysis.allowed)
        self.assertIn("rebound confirmation", analysis.reason)

    def test_confirmation_allows_recent_rebound(self):
        closes = [100 - i * 0.08 for i in range(70)]
        closes += [94.4 + i * 0.09 for i in range(27)]
        analysis = analyze_pre_trade_klines("BTC", _klines_from_closes(closes))
        self.assertTrue(analysis.allowed, analysis.reason)

    def test_bad_ohlc_cannot_produce_run(self):
        for bad in ("nan", "inf", "0", "-1", "not-a-price"):
            rows = _klines_from_closes([100.0] * 97)
            rows[-1][4] = bad
            self.assertFalse(analyze_pre_trade_klines("BTC", rows).allowed)


class TestClosedCandles(unittest.TestCase):
    def test_discards_forming_candle(self):
        rows = _klines_from_closes([100] * 5)
        forming = list(rows[-1])
        forming[0] += 900_000
        forming[6] += 900_000
        forming[4] = "999999"
        self.assertEqual(closed_candles(rows + [forming], "15m", 5), rows)

    def test_rejects_stale_data(self):
        rows = _klines_from_closes([100] * 5)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        with self.assertRaisesRegex(ValueError, "stale"):
            closed_candles(rows, "15m", 5, future)

    def test_rejects_gap_or_duplicate(self):
        rows = _klines_from_closes([100] * 6)
        with self.assertRaises(ValueError):
            closed_candles(rows[:2] + rows[3:], "15m", 5)
        with self.assertRaises(ValueError):
            closed_candles(rows + [rows[-1]], "15m", 5)

    def test_rejects_nonfinite_prices(self):
        rows = _klines_from_closes([100] * 5)
        rows[-1][4] = "nan"
        with self.assertRaises(ValueError):
            closed_candles(rows, "15m", 5)

    def test_rejects_other_interval_and_short_window(self):
        with self.assertRaises(ValueError):
            closed_candles(_klines_from_closes([100] * 5), "1h", 5)
        with self.assertRaises(ValueError):
            closed_candles(_klines_from_closes([100] * 4), "15m", 5)


class TestPerformanceAccounting(unittest.TestCase):
    def setUp(self):
        isolate_data_dir(self)
        config.CAPITAL_USD = 10_000
        config.LEVERAGE = 20
        config.FUTURES_NET_TP_PCT = 0.01
        config.FUTURES_FEE_PCT = 0.0006
        config.FUNDING_RATE_DAILY = 0.0003
        config.MONTHLY_CONTRIBUTION_USD = 0
        config.FUTURES_USE_SL = False
        self.trader = FuturesTrader()

    def test_high_win_rate_does_not_mask_negative_expectancy(self):
        self.trader.positions = [SimpleNamespace(status=FuturesPositionStatus.TP_HIT,
            pnl_usd=1, pnl_pct=1, funding_paid=0) for _ in range(9)]
        self.trader.positions.append(SimpleNamespace(status=FuturesPositionStatus.EXPIRED,
            pnl_usd=-50, pnl_pct=-50, funding_paid=0))
        stats = self.trader.get_stats()
        self.assertEqual(stats["win_rate"], 90)
        self.assertEqual(stats["total_net_pnl_usd"], -41)
        self.assertEqual(stats["expectancy_usd"], -4.1)
        self.assertEqual(stats["avg_win_usd"], 1)
        self.assertEqual(stats["avg_loss_usd"], 50)
        self.assertAlmostEqual(stats["profit_factor"], 0.18)

    def test_empty_statistics_are_defined_without_infinity(self):
        stats = self.trader.get_stats()
        self.assertIsNone(stats["profit_factor"])
        self.assertEqual(stats["expectancy_usd"], 0)

    def test_tp_delivers_exact_net_target_after_long_hold(self):
        with patch.object(self.trader, "get_current_price", return_value=100):
            pos = self.trader.open_position("BTC", margin_usd=100)
        now = pos.entry_time + timedelta(days=30)
        target = self.trader._net_tp_price(pos, now)
        self.trader._close(pos, target, FuturesPositionStatus.TP_HIT, now)
        self.assertAlmostEqual(pos.pnl_pct, 1.0, places=8)

    def test_entry_target_and_costs_survive_settings_change_and_restart(self):
        with patch.object(self.trader, "get_current_price", return_value=100):
            pos = self.trader.open_position("BTC", margin_usd=100)
        now = pos.entry_time + timedelta(days=2)
        target = self.trader._net_tp_price(pos, now)
        config.FUTURES_NET_TP_PCT = 0.05
        config.FUTURES_FEE_PCT = 0.001
        config.FUNDING_RATE_DAILY = 0.005
        reloaded = FuturesTrader()
        restored = reloaded.get_open_positions()[0]
        self.assertAlmostEqual(reloaded._net_tp_price(restored, now), target)
        reloaded._close(restored, target, FuturesPositionStatus.TP_HIT, now)
        self.assertAlmostEqual(restored.pnl_pct, 1.0, places=8)

    def test_appending_legacy_history_preserves_column_alignment(self):
        path = _history_csv()
        fields = ["symbol", "pnl_usd", "reason"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"symbol": "BTC", "pnl_usd": "-5", "reason": "expired"})
        before = path.read_bytes()
        _append_trade_csv({"symbol": "ETH", "pnl_usd": 1, "reason": "tp_hit", "entry_fee": 0.1})
        self.assertTrue(path.read_bytes().startswith(before))
        with path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[-1], {"symbol": "ETH", "pnl_usd": "1", "reason": "tp_hit"})


if __name__ == "__main__":
    unittest.main()
