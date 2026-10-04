"""Offline Windows UI smoke check; never touches the user's paper account."""

import tempfile
import ctypes
from pathlib import Path
from unittest.mock import patch

from PIL import ImageGrab

from bot import config
from bot.dashboard import Dashboard
from bot.modules.futures_trader import FuturesTrader
from bot.modules.strategy import Strategy


def run():
    with tempfile.TemporaryDirectory() as tmp:
        config.DATA_DIR = Path(tmp)
        config.PROJECT_ROOT = Path(tmp)
        config.CAPITAL_USD = 500
        config.LOCAL_BRIDGE_ENABLED = False
        config.AUTO_START_FUTURES = False
        config.SETTINGS_CONFIRMED = True
        config.TELEGRAM_BOT_TOKEN = ""
        config.TELEGRAM_CHAT_ID = ""
        config.OHVERLAY_ENABLED = False
        with (patch.object(Dashboard, "_start_trading_loop"),
              patch.object(Dashboard, "_start_telegram_dashboard"),
              patch.object(Dashboard, "_schedule_refresh")):
            app = Dashboard(Strategy(trader=FuturesTrader()))
            try:
                for size in ("1100x720", "1280x840"):
                    app.root.geometry(size)
                    app.notebook.select(app.settings_tab)
                    app.root.update()
                    app._update_stats()
                    assert "Realized $+0.00" in app.profit_breakdown_var.get()
                    assert "Open net est." in app.profit_breakdown_var.get()
                    assert app._s_require_dip.get()
                    assert app._s_confirm_rebound.get()
                    tabs = [app.notebook.tab(t, "text").strip() for t in app.notebook.tabs()]
                    assert not any("P2P" in label for label in tabs)
                    assert not hasattr(app, "contrib_tree")
                    assert not hasattr(app, "p2p_monitor")
                    parent = app.settings_tab
                    canvas = next(w for w in parent.winfo_children() if w.winfo_class() == "Canvas")
                    canvas.yview_moveto(1)
                    app.root.update()
                    assert canvas.bbox("all")[3] > 0
                    buttons = []

                    def collect(w):
                        for child in w.winfo_children():
                            if child.winfo_class() == "TButton" and child.cget("text") == "Apply Settings":
                                buttons.append(child)
                            collect(child)

                    collect(parent)
                    button = buttons[0]
                    assert button.winfo_rooty() >= canvas.winfo_rooty()
                    assert button.winfo_rooty() + button.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
                    app.notebook.select(3)
                    app._refresh_history()
                    app.root.update()
                    assert "Expectancy" in app._hist_metrics_var.get()
                    print(f"UI PASS {size}: settings scroll, Apply Settings reachable, History metrics render")
                # PrintWindow targets the app even when another window covers it.
                hwnd = ctypes.windll.user32.GetAncestor(app.root.winfo_id(), 2)
                output = Path("build/ui-entry-quality-history.png")
                output.parent.mkdir(exist_ok=True)
                ImageGrab.grab(window=hwnd).save(output)
                print(f"Screenshot: {output.resolve()}")
                app.notebook.select(app.settings_tab)
                canvas.yview_moveto(0)
                app.root.update()
                output = Path("build/ui-entry-quality-settings.png")
                ImageGrab.grab(window=hwnd).save(output)
                print(f"Screenshot: {output.resolve()}")
            finally:
                app.root.destroy()


if __name__ == "__main__":
    run()
