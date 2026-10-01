"""Binance USD-M futures testnet order validation helpers.

This module never submits an order to the matching engine. It uses Binance
`futures_create_test_order` to validate signed order payloads and credentials.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

from binance.client import Client as BinanceClient


class BinanceTestnetProbe:
    def __init__(self, api_key: str, api_secret: str, client=None):
        self.client = client or BinanceClient(api_key, api_secret, testnet=True)

    @staticmethod
    def pair(symbol: str) -> str:
        symbol = (symbol or "").upper()
        return symbol if symbol.endswith("USDT") else f"{symbol}USDT"

    def _symbol_info(self, symbol: str) -> dict:
        pair = self.pair(symbol)
        info = self.client.futures_exchange_info()
        for row in info.get("symbols", []):
            if row.get("symbol") == pair:
                return row
        raise ValueError(f"Unknown futures symbol: {pair}")

    def quantity_from_notional(self, symbol: str, notional_usd: float) -> float:
        if notional_usd <= 0:
            raise ValueError("notional_usd must be positive")
        pair = self.pair(symbol)
        ticker = self.client.futures_symbol_ticker(symbol=pair)
        price = Decimal(str(ticker["price"]))
        if price <= 0:
            raise ValueError(f"Invalid market price for {pair}")

        info = self._symbol_info(pair)
        filters = {f["filterType"]: f for f in info.get("filters", [])}
        lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE")
        if not lot:
            raise ValueError(f"No lot-size filter for {pair}")

        step = Decimal(str(lot["stepSize"]))
        minimum = Decimal(str(lot["minQty"]))
        maximum = Decimal(str(lot["maxQty"]))
        raw = Decimal(str(notional_usd)) / price
        quantity = (raw / step).to_integral_value(rounding=ROUND_DOWN) * step
        if quantity < minimum:
            raise ValueError(f"Quantity {quantity} below {pair} minimum {minimum}")
        if quantity > maximum:
            raise ValueError(f"Quantity {quantity} above {pair} maximum {maximum}")
        return float(quantity)

    def validate_market_order(
        self,
        symbol: str,
        side: str,
        *,
        quantity: float | None = None,
        notional_usd: float | None = None,
    ):
        side = (side or "").upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if quantity is None:
            if notional_usd is None:
                raise ValueError("quantity or notional_usd is required")
            quantity = self.quantity_from_notional(symbol, notional_usd)
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        return self.client.futures_create_test_order(
            symbol=self.pair(symbol),
            side=side,
            type="MARKET",
            quantity=quantity,
        )