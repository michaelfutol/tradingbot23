"""OKX USDT swap market data and read-only demo-account verification.

No exchange order, transfer, withdrawal or production account endpoint exists.
"""

import base64
import hashlib
import hmac
import math
import re
import time
from datetime import datetime, timezone

import requests

from bot import config


class OKXBridge:
    BASE = "https://www.okx.com"
    INTERVALS = {"5m": ("5m", 300000), "15m": ("15m", 900000),
                 "1h": ("1H", 3600000), "1d": ("1Dutc", 86400000)}

    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.trust_env = False
        self._instruments = None
        self._instrument_ts = 0.0

    def _get(self, path, params=None, headers=None):
        response = self.session.get(self.BASE + path, params=params,
                                    headers=headers, timeout=15, allow_redirects=False)
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
            raise ValueError("OKX request rejected; check account or instrument configuration")
        return payload["data"]

    def instrument(self, pair):
        if not re.fullmatch(r"[A-Z0-9]{2,20}USDT", pair):
            raise ValueError("Only USDT perpetual instruments are supported")
        inst_id = pair[:-4] + "-USDT-SWAP"
        if self._instruments is None or time.monotonic() - self._instrument_ts > 3600:
            rows = self._get("/api/v5/public/instruments", {"instType": "SWAP"})
            self._instruments = {row["instId"]: row for row in rows
                                 if row.get("state") == "live" and row.get("settleCcy") == "USDT"
                                 and row.get("ctType") == "linear"}
            self._instrument_ts = time.monotonic()
        if inst_id not in self._instruments:
            raise ValueError("No active OKX linear USDT swap for this symbol")
        return inst_id

    def futures_symbol_ticker(self, *, symbol):
        inst_id = self.instrument(symbol)
        rows = self._get("/api/v5/public/mark-price", {"instType": "SWAP", "instId": inst_id})
        if len(rows) != 1 or rows[0].get("instId") != inst_id:
            raise ValueError("OKX mark instrument mismatch")
        price = float(rows[0]["markPx"])
        age_ms = time.time() * 1000 - float(rows[0]["ts"])
        if not math.isfinite(price) or price <= 0 or not -30000 <= age_ms <= 120000:
            raise ValueError("OKX mark is invalid or stale")
        return {"price": price}

    def futures_klines(self, *, symbol, interval, limit):
        bar, duration = self.INTERVALS[interval]
        if not 2 <= limit <= 300:
            raise ValueError("Candle limit must be 2-300")
        rows = self._get("/api/v5/market/candles",
                         {"instId": self.instrument(symbol), "bar": bar, "limit": limit})
        candles = []
        for row in rows:
            # OKX returns newest first; confirm=0 is the forming candle.
            if len(row) < 9 or row[8] != "1":
                continue
            stamp = int(row[0])
            candles.append([stamp, *row[1:6], stamp + duration - 1])
        return sorted(candles, key=lambda row: row[0])

    def verify_demo_account(self):
        if not all((config.OKX_API_KEY, config.OKX_API_SECRET, config.OKX_API_PASSPHRASE)):
            raise ValueError("Set OKX demo API key, secret and passphrase in the private .env")
        stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        path = "/api/v5/account/config"
        signature = base64.b64encode(hmac.new(config.OKX_API_SECRET.encode(),
                                             (stamp + "GET" + path).encode(), hashlib.sha256).digest()).decode()
        rows = self._get(path, headers={"OK-ACCESS-KEY": config.OKX_API_KEY,
                         "OK-ACCESS-SIGN": signature, "OK-ACCESS-TIMESTAMP": stamp,
                         "OK-ACCESS-PASSPHRASE": config.OKX_API_PASSPHRASE,
                         "x-simulated-trading": "1"})
        if len(rows) != 1:
            raise ValueError("Invalid OKX demo configuration")
        return {"exchange": "okx", "environment": "demo", "verified": True,
                "account_level": rows[0].get("acctLv"), "position_mode": rows[0].get("posMode"),
                "order_execution_enabled": False}
