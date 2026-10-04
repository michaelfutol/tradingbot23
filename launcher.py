"""EXE entry point for TradingBot23.

When double-clicked:
  1. If no .env found -> shows setup wizard (GUI)
  2. Loads config from .env
  3. Opens the dashboard with futures paper trading running
"""

import sys
import os
from pathlib import Path

if "--bridge" in sys.argv:
    sys.argv.remove("--bridge")
    from bot.bridge_cli import main as bridge_main
    bridge_main()
    sys.exit(0)

if getattr(sys, "frozen", False):
    os.chdir(Path(sys.executable).parent)
    os.environ.setdefault("DOTENV_PATH", str(Path(sys.executable).parent / ".env"))

from bot.setup_wizard import ensure_setup

if not ensure_setup():
    print("Setup cancelled. Exiting.")
    input("Press Enter to close...")
    sys.exit(0)

import logging
from bot import config
from bot.modules.data_fetcher import DataFetcher
from bot.modules.futures_trader import FuturesTrader
from bot.modules.strategy import Strategy

log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
log_file = config.LOG_DIR / "bot_gui.log"
logging.basicConfig(level=logging.INFO, format=log_format,
                    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)])

try:
    config.validate()
except ValueError as e:
    print(f"Config error: {e}")
    input("Press Enter to close...")
    sys.exit(1)

from bot.dashboard import Dashboard
from bot.modules.account_lock import AccountLock

if __name__ == "__main__":
    try:
        with AccountLock(config.DATA_DIR):
            strategy = Strategy(fetcher=DataFetcher(), trader=FuturesTrader())
            dashboard = Dashboard(strategy)
            dashboard.run()
    except KeyboardInterrupt:
        print("\nBot stopped.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to close...")
