"""Offline API fixture for browser smoke checks. Never a production entrypoint."""

from datetime import datetime, timezone

import uvicorn

from bot import api
from bot.modules.futures_trader import FuturesPositionStatus
from tests.test_api import TestPaperAPI


def main():
    fixture = TestPaperAPI()
    fixture.setUp()
    fixture.trader.cash_balance = 899.0
    fixture.trader.positions = [
        fixture.position(),
        fixture.position(symbol="ETH", status=FuturesPositionStatus.TP_HIT,
                         exit_price=102.0, exit_time=datetime.now(timezone.utc),
                         pnl_pct=1.25, pnl_usd=1.25),
    ]
    try:
        uvicorn.run(api.app, host="127.0.0.1", port=8000, access_log=False)
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
