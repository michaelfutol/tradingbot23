"""Validated, completed Binance candles for entry decisions."""

import math
from datetime import datetime, timezone


def closed_candles(klines: list, interval: str, count: int,
                   now: datetime | None = None) -> list:
    """Reject gaps/stale or malformed data; never use the forming candle."""
    if interval != "15m":
        raise ValueError("entry analysis requires 15m candles")
    if count < 2:
        raise ValueError("at least two completed candles required")
    step = 15 * 60 * 1000
    now_ms = int((now or datetime.now(timezone.utc)).timestamp() * 1000)
    completed = []
    for row in klines:
        if len(row) < 7:
            raise ValueError("missing candle timestamps")
        opened, closed = int(row[0]), int(row[6])
        if closed >= now_ms:
            continue
        values = [float(row[i]) for i in range(1, 6)]
        o, h, l, c, volume = values
        if (not all(math.isfinite(v) for v in values)
                or min(o, h, l, c) <= 0 or volume < 0
                or not l <= min(o, c) <= max(o, c) <= h
                or closed - opened != step - 1):
            raise ValueError("invalid candle OHLC or duration")
        if completed and opened - int(completed[-1][0]) != step:
            raise ValueError("duplicate, out-of-order or missing candles")
        completed.append(row)
    if len(completed) < count:
        raise ValueError("not enough completed candles")
    if now_ms - int(completed[-1][6]) > step:
        raise ValueError("stale completed candles")
    return completed[-count:]
