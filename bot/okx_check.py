"""Verify OKX public connectivity or a read-only demo key; never submits orders."""

import argparse
import json

from bot.modules.okx_bridge import OKXBridge


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Verify the configured demo-account key")
    args = parser.parse_args()
    try:
        bridge = OKXBridge()
        result = bridge.verify_demo_account() if args.demo else {
            "exchange": "okx", "instrument": "BTC-USDT-SWAP",
            "mark": bridge.futures_symbol_ticker(symbol="BTCUSDT")["price"],
            "completed_15m_candles": len(bridge.futures_klines(symbol="BTCUSDT", interval="15m", limit=6)),
            "order_execution_enabled": False}
        print(json.dumps(result, indent=2))
    except Exception:
        parser.exit(1, "OKX verification failed. Check connectivity, instrument availability or your private demo configuration.\n")


if __name__ == "__main__":
    main()
