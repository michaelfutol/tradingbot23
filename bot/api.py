"""Authenticated, paper-only API. Run one worker against a private data directory."""

import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from bot import config
from bot.modules.data_fetcher import DataFetcher
from bot.modules.futures_trader import FuturesTrader
from bot.modules.strategy import Strategy
from bot.modules.account_lock import AccountLock

logger = logging.getLogger(__name__)
_security = HTTPBasic(auto_error=False)
_strategy_instance = None
_state_lock = threading.RLock()


def require_user(credentials: HTTPBasicCredentials | None = Depends(_security)):
    username = os.getenv("WEB_USERNAME", "")
    password = os.getenv("WEB_PASSWORD", "")
    if not username or len(password) < 16:
        raise HTTPException(503, "Web access is not configured.")
    user_ok = secrets.compare_digest(
        (credentials.username if credentials else "").encode(), username.encode()
    )
    password_ok = secrets.compare_digest(
        (credentials.password if credentials else "").encode(), password.encode()
    )
    if not (user_ok and password_ok):
        raise HTTPException(401, "Sign-in required.", headers={"WWW-Authenticate": 'Basic realm="Trade23"'})


def get_strategy() -> Strategy:
    global _strategy_instance
    with _state_lock:
        if _strategy_instance is None:
            config.validate()
            if config.TRADING_MODE != "paper":
                raise ValueError("The web API supports paper trading only.")
            _strategy_instance = Strategy(fetcher=DataFetcher(), trader=FuturesTrader())
        return _strategy_instance


@asynccontextmanager
async def lifespan(app):
    if not os.getenv("WEB_USERNAME") or len(os.getenv("WEB_PASSWORD", "")) < 16:
        raise RuntimeError("Set WEB_USERNAME and a WEB_PASSWORD of at least 16 characters.")
    with AccountLock(config.DATA_DIR):
        get_strategy()
        logger.info("Authenticated paper API started; one worker required.")
        yield


app = FastAPI(title="TradingBot23 API", version="1.0.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None,
              dependencies=[Depends(require_user)])
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("WEB_ALLOWED_ORIGINS", "").split(",")
                   if origin.strip() and origin.strip() != "*"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def private_responses(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def _open_position(pos, now):
    estimate = FuturesTrader.estimate_position_pnl(pos, now)
    return {
        "symbol": pos.symbol, "entry_price": pos.entry_price,
        "leverage": pos.leverage, "margin_used": pos.margin_used, "notional": pos.notional,
        "pnl_pct": estimate["pnl_pct"], "pnl_usd": estimate["pnl_usd"],
        "tp_price": pos.tp_price, "liquidation_price": pos.liquidation_price,
        "last_known_price": estimate["mark_price"], "age_days": estimate["age_days"],
        "estimated_exit_cost_usd": estimate["exit_fee_usd"] + estimate["funding_usd"],
    }


@app.get("/api/status")
def get_status():
    with _state_lock:
        strategy = get_strategy()
        status = strategy.get_status()
        now = datetime.now(timezone.utc)
        positions = [_open_position(pos, now) for pos in strategy.trader.get_open_positions()]
        return {
            "mode": "paper", "portfolio_value": status["portfolio_value"],
            "estimated_net_equity": status["portfolio_value"] - sum(
                pos["estimated_exit_cost_usd"] for pos in positions),
            "cash_balance": status["cash_balance"], "open_positions": positions,
            "stats": status["stats"], "basket": status["basket"],
            "price_source": "cached futures marks", "as_of": now.isoformat(),
        }


@app.get("/api/history")
def get_history():
    with _state_lock:
        trader = get_strategy().trader
        history = [{
            "symbol": trade.symbol, "entry_price": trade.entry_price,
            "exit_price": trade.exit_price, "pnl_pct": trade.pnl_pct, "pnl_usd": trade.pnl_usd,
            "reason": trade.status.value, "leverage": trade.leverage,
            "exit_date": trade.exit_time.isoformat() if trade.exit_time else None,
        } for trade in reversed(trader.get_trade_history()[-50:])]
        return {"stats": trader.get_stats(), "history": history}


@app.post("/api/cron/run_cycle")
def run_cycle():
    if os.getenv("WEB_ENABLE_CYCLES", "false").lower() != "true":
        raise HTTPException(403, "Remote paper cycles are disabled.")
    if not _state_lock.acquire(blocking=False):
        raise HTTPException(409, "A portfolio operation is already running.")
    try:
        return {"status": "success", "summary": get_strategy().run_cycle()}
    except Exception:
        logger.exception("Paper cycle failed")
        raise HTTPException(500, "Paper cycle failed; consult the private server log.") from None
    finally:
        _state_lock.release()


@app.get("/api/config")
def get_config():
    return {
        "TRADING_MODE": "paper", "CAPITAL_USD": config.CAPITAL_USD,
        "LEVERAGE": config.LEVERAGE, "FUTURES_NET_TP_PCT": config.FUTURES_NET_TP_PCT,
        "FUTURES_USE_SL": config.FUTURES_USE_SL, "MAX_HOLD_DAYS": config.MAX_HOLD_DAYS,
        "PER_TRADE_PCT": config.PER_TRADE_PCT, "MAX_OPEN_TRADES": config.MAX_OPEN_TRADES,
    }
