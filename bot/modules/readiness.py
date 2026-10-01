"""Automated forward-test readiness metrics for TradingBot23."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bot import config
from bot.modules.futures_trader import FuturesPositionStatus


def _max_loss_streak(trades) -> int:
    streak = 0
    maximum = 0
    for trade in trades:
        if trade.pnl_usd < 0:
            streak += 1
            maximum = max(maximum, streak)
        else:
            streak = 0
    return maximum


def _max_drawdown_pct(trades, starting_capital: float) -> float:
    equity = float(starting_capital)
    peak = max(equity, 0.0)
    maximum = 0.0
    for trade in trades:
        equity += float(trade.pnl_usd)
        peak = max(peak, equity)
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak * 100)
    return maximum


def build_readiness_report(trader) -> dict:
    """Build an auditable live-test gate from closed forward trades."""
    trades = [
        t for t in trader.get_trade_history()
        if t.status != FuturesPositionStatus.EXCLUDED
    ]
    trades.sort(key=lambda t: t.exit_time or t.entry_time)

    pnls = [float(t.pnl_usd) for t in trades]
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    expectancy = (sum(pnls) / len(pnls)) if pnls else 0.0
    wins = sum(1 for p in pnls if p > 0)
    liquidations = sum(
        1 for t in trades if t.status == FuturesPositionStatus.LIQUIDATED
    )
    contributed = max(float(trader.get_contributed_capital()), 0.01)
    drawdown = _max_drawdown_pct(trades, contributed)
    loss_streak = _max_loss_streak(trades)

    checks = {
        "sample_size": len(trades) >= config.READINESS_MIN_TRADES,
        "positive_expectancy": expectancy > config.READINESS_MIN_EXPECTANCY_USD,
        "profit_factor": (
            gross_profit > 0
            if profit_factor is None
            else profit_factor >= config.READINESS_MIN_PROFIT_FACTOR
        ),
        "drawdown": drawdown <= config.READINESS_MAX_DRAWDOWN_PCT,
        "loss_streak": loss_streak <= config.READINESS_MAX_LOSS_STREAK,
        "liquidations": liquidations <= config.READINESS_MAX_LIQUIDATIONS,
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds": {
            "min_trades": config.READINESS_MIN_TRADES,
            "min_expectancy_usd": config.READINESS_MIN_EXPECTANCY_USD,
            "min_profit_factor": config.READINESS_MIN_PROFIT_FACTOR,
            "max_drawdown_pct": config.READINESS_MAX_DRAWDOWN_PCT,
            "max_loss_streak": config.READINESS_MAX_LOSS_STREAK,
            "max_liquidations": config.READINESS_MAX_LIQUIDATIONS,
        },
        "metrics": {
            "trades": len(trades),
            "wins": wins,
            "losses": len(trades) - wins,
            "win_rate_pct": (wins / len(trades) * 100) if trades else 0.0,
            "net_pnl_usd": sum(pnls),
            "expectancy_usd": expectancy,
            "gross_profit_usd": gross_profit,
            "gross_loss_usd": gross_loss,
            "profit_factor": profit_factor,
            "max_drawdown_pct": drawdown,
            "max_loss_streak": loss_streak,
            "liquidations": liquidations,
        },
    }


def save_readiness_report(trader, path: Path | None = None) -> Path:
    path = path or (config.DATA_DIR / "readiness_report.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_readiness_report(trader), indent=2),
        encoding="utf-8",
    )
    return path


def format_readiness_report(report: dict) -> str:
    metrics = report["metrics"]
    pf = metrics["profit_factor"]
    pf_text = "n/a" if pf is None else f"{pf:.2f}"
    state = "PASS" if report["passed"] else "NOT READY"
    failed = [name for name, ok in report["checks"].items() if not ok]
    return (
        f"Trade23 readiness: {state}\n"
        f"Trades: {metrics['trades']} | Win rate: {metrics['win_rate_pct']:.1f}% | "
        f"Net P&L: ${metrics['net_pnl_usd']:+.2f}\n"
        f"Expectancy: ${metrics['expectancy_usd']:+.3f}/trade | "
        f"Profit factor: {pf_text}\n"
        f"Max drawdown: {metrics['max_drawdown_pct']:.2f}% | "
        f"Max loss streak: {metrics['max_loss_streak']} | "
        f"Liquidations: {metrics['liquidations']}\n"
        f"Failed gates: {', '.join(failed) if failed else 'none'}"
    )