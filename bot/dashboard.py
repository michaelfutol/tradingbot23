"""Live dashboard for TradingBot23."""

import logging
import math
import queue
import threading
import time
import tkinter as tk
from collections import defaultdict
from datetime import datetime, timezone
from tkinter import messagebox, ttk

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import csv as _csv

from bot import config
from bot.ui_theme import (BG, MUTED, FONT, SUCCESS, DANGER, configure_styles,
                          apply_window_brand, asset_path)
import rebound_duration_analysis as rebound_analysis
from bot.modules.local_bridge import LocalBridge
from bot.modules import ohverlay_notifier as ov
from bot.modules import telegram_notifier as tg
from bot.modules.event_ledger import EventLedger, append_event
from bot.modules.futures_trader import _history_csv, recent_reset_sessions

logger = logging.getLogger(__name__)


class ToolTip:
    """Small hover tooltip for tkinter/ttk controls."""

    def __init__(self, widget, text: str, delay_ms: int = 550, wraplength: int = 420):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.wraplength = wraplength
        self._after_id = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<FocusIn>", self._schedule, add="+")
        widget.bind("<FocusOut>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if self._window or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 18
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        except tk.TclError:
            return

        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self._window,
            text=self.text,
            justify="left",
            bg="#24282c",
            fg="#f5f7f8",
            relief="solid",
            bd=1,
            padx=9,
            pady=7,
            wraplength=self.wraplength,
            font=(FONT, 9),
        )
        label.pack()
        self._window.update_idletasks()
        width, height = self._window.winfo_reqwidth(), self._window.winfo_reqheight()
        x = max(8, min(x, self.widget.winfo_screenwidth() - width - 8))
        if y + height > self.widget.winfo_screenheight() - 8:
            y = max(8, self.widget.winfo_rooty() - height - 8)
        self._window.wm_geometry(f"+{x}+{y}")

    def _hide(self, _event=None):
        self._cancel()
        if self._window:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None


SETTINGS_HELP = {
    "Capital (USD)": "Total paper deposits, not a fresh balance or a base plus monthly additions. Apply adds or withdraws the difference from free cash; trading profits/losses and open positions are retained. Use Reset Futures Paper for a fresh session.",
    "Account exposure (x)": "Maximum TOTAL leveraged notional divided by estimated net equity. 3x means a $100 account can hold at most $300 total notional, even with 20x entries. Zero disables this cap. It blocks/sizes new entries, never force-closes trades.",
    "Cash reserve (%)": "Minimum share of net equity retained as free cross-margin cash. This reduces exposure but cannot prevent liquidation in a severe crash.",
    "Futures exchange": "OKX uses live public linear USDT perpetual marks and completed candles; no API key is needed for paper. Binance is retained for compatibility. Change only with no open positions.",
    "Leverage": "Leverage used for new futures paper trades only. Higher leverage magnifies both profit and drawdown. Existing trades keep their entry leverage.",
    "TP target (% net)": "Net take-profit target on margin after estimated fees and funding. The app calculates the required price move for each new trade.",
    "Stop Loss": "Optional hard stop-loss. When disabled, positions rely on TP, max-hold expiry, and cross-margin liquidation tracking.",
    "Crash protection": "Block entries pauses new futures longs when BTC is dumping. Emergency SL force-closes existing positions during crash mode, so use it only when you intentionally want an anti-crash stop.",
    "BTC filter (% 1h)": "Market-regime gate for long entries. Example: -1.5 blocks new trades when BTC is down 1.5% or worse over roughly 1 hour. Blank or 'none' disables it.",
    "Max hold (days)": "Maximum age of a futures paper position before it is closed at market in the simulation.",
    "Per trade (% of portfolio)": "Margin size for each new trade as a percent of current paper portfolio value. This is margin, not leveraged notional.",
    "Max open trades": "Maximum simultaneous futures paper positions. Lowering this does not force-close existing trades; it only blocks new entries until open count drops.",
    "Pre-trade wave check": "Before opening a futures trade, inspect the coin's recent 15m candles to avoid entries still making fresh lows.",
    "Min pre-trade score": "Minimum 0-100 wave score required before entry. Higher is stricter and opens fewer trades.",
    "Require dip": "When enabled, empty slots wait until the configured 24h dip threshold is met. Disable only to restore the old always-invested refill policy.",
    "Confirm rebound": "Requires two rising completed 15m closes, positive 1h momentum and a close above SMA20. This is a quality filter, not a prediction or a guaranteed win rate.",
    "Auto-start futures": "When enabled, futures scanning resumes automatically on app launch after settings are confirmed.",
    "Ohverlay alerts": "Send short local bubble notifications to Ohverlay v4 via localhost webhook. Requires Ohverlay's Webhook Server to be enabled.",
}

RISK_HELP = {
    "Profile": "Local data profile name. Different profiles use separate data folders after restart, useful for beta testers.",
    "Max daily loss $": "Risk guard. Zero disables it. If today's closed futures P&L falls below this loss, new entries are blocked.",
    "Max open notional $": "Risk guard. Zero disables it. Blocks new entries once leveraged open notional reaches this dollar limit.",
    "Max loss streak": "Risk guard. Zero disables it. Blocks new entries after this many consecutive losing closed futures trades.",
}



class Dashboard:
    REFRESH_MS = 2000

    def __init__(self, strategy):
        self.strategy = strategy
        self.trader   = strategy.trader
        self._running      = True
        self._settings_confirmed = config.SETTINGS_CONFIRMED
        self._paused       = (not config.AUTO_START_FUTURES) or (not self._settings_confirmed)
        self._force_event  = threading.Event()
        self._cycle_thread = None
        self._account_lock = threading.RLock()
        self._one_shot_requested = False
        self._bridge = None
        self._bridge_scan_id = None

        self._last_cycle_time:    datetime | None = None
        self._last_cycle_summary: dict = {}
        self._next_cycle_ts:      float = 0.0
        self.event_ledger = EventLedger()
        self._telegram_commands = None
        self._risk_kill_switch = False
        self._decision_log: list[dict[str, str]] = []
        self._rebound_study_running = False
        self._risk_panes = None

        logger.info(
            "Dashboard startup | auto_start=%s settings_confirmed=%s paused=%s data_dir=%s",
            config.AUTO_START_FUTURES,
            self._settings_confirmed,
            self._paused,
            config.DATA_DIR,
        )

        # Equity history: list of (datetime, portfolio_value)
        self._equity_history: list[tuple[datetime, float]] = []
        self._equity_lock = threading.Lock()

        self.root = tk.Tk()
        self.root.title("Trade23")
        width = min(1280, self.root.winfo_screenwidth() - 64)
        height = min(840, self.root.winfo_screenheight() - 96)
        self.root.geometry(f"{width}x{height}+24+16")
        self.root.minsize(min(960, width), min(640, height))
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._start_local_bridge()
        self._start_telegram_dashboard()
        self._start_trading_loop()
        self._schedule_refresh()

    # ── UI construction ────────────────────────────────────────────────────────

    def _tip(self, widget, text: str):
        tip = ToolTip(widget, text)
        try:
            widget._tradingbot_tooltip = tip
        except Exception:
            pass
        return widget

    def _build_ui(self):
        configure_styles(self.root)
        apply_window_brand(self.root)
        self._icons = {name: tk.PhotoImage(master=self.root, file=str(asset_path(path)))
            for name, path in {
                "brand": "ui/mark-40.png", "play": "ui/play-light.png",
                "run": "ui/play-dark.png", "pause": "ui/pause-light.png",
                "send": "ui/send-light.png", "refresh": "ui/refresh-light.png",
                "download": "ui/download-light.png", "reset": "ui/reset-light.png",
                "save": "ui/save-dark.png",
            }.items()}

        top = tk.Frame(self.root, bg=BG, padx=24, pady=16)
        top.pack(fill="x")
        tk.Label(top, image=self._icons["brand"], bg=BG).pack(side="left", padx=(0, 12))
        brand = tk.Frame(top, bg=BG)
        brand.pack(side="left")
        ttk.Label(brand, text="Trade23", font=(FONT, 18, "bold")).pack(anchor="w")
        self.engine_var = tk.StringVar(value=self._new_trade_setting_text())
        ttk.Label(brand, textvariable=self.engine_var, foreground=MUTED,
                  font=(FONT, 9)).pack(anchor="w")
        self.clock_label = ttk.Label(top, text="", foreground=MUTED, font=(FONT, 9))
        self.clock_label.pack(side="right")
        self.mode_label = ttk.Label(top, text="PAPER", style="Mode.TLabel")
        self.mode_label.pack(side="right", padx=(0, 22))
        self._tip(self.mode_label, "Paper simulation only. No real exchange orders are enabled.")

        ctrl = tk.Frame(self.root, bg=BG, padx=24, pady=4)
        ctrl.pack(fill="x")
        self.run_btn = ttk.Button(ctrl, text="Run Now", image=self._icons["run"],
                                  compound="left", style="Primary.TButton", command=self._on_run_now)
        self.pause_btn = ttk.Button(ctrl, text="Resume" if self._paused else "Pause",
            image=self._icons["play" if self._paused else "pause"], compound="left",
            style="Btn.TButton", command=self._on_pause_resume)
        self.run_btn.pack(side="left", padx=(0, 8))
        self.pause_btn.pack(side="left", padx=(0, 8))
        self._tip(self.run_btn, "Request one guarded paper scan. Exits are checked first; entries still require fresh data and risk approval.")
        self._tip(self.pause_btn, "Pause stops new entries while existing positions are monitored for exits. Resume enables scheduled scans.")
        tg_menu_btn = ttk.Button(ctrl, image=self._icons["send"], width=3,
                                style="Btn.TButton", command=self._send_telegram_menu)
        tg_menu_btn.pack(side="left")
        self._tip(tg_menu_btn, "Send the dashboard menu to your configured Telegram chat.")
        self._run_state_var = tk.StringVar(value="Paused" if self._paused else "Running")
        ttk.Label(ctrl, textvariable=self._run_state_var, foreground=MUTED,
                  font=(FONT, 9)).pack(side="right")

        initial = ("Review Settings before starting." if not self._settings_confirmed
                   else "Entries paused." if self._paused else "Starting...")
        self.status_var = tk.StringVar(value=initial)
        status_frame = tk.Frame(self.root, bg=BG, height=44)
        status_frame.pack(fill="x")
        status_frame.pack_propagate(False)
        status_label = ttk.Label(status_frame, textvariable=self.status_var, foreground=MUTED,
                                 font=(FONT, 9), padding=(24, 8))
        status_label.pack(fill="both", expand=True)
        status_label.bind("<Configure>", lambda e: status_label.configure(wraplength=max(100, e.width - 48)))
        ttk.Separator(self.root).pack(fill="x", padx=24)

        stats_frame = tk.Frame(self.root, bg=BG, padx=24, pady=18)
        stats_frame.pack(fill="x")
        self.portfolio_var = tk.StringVar(value="$0.00")
        self.cash_var = tk.StringVar(value="$0.00")
        self.pnl_var = tk.StringVar(value="+0.00%")
        self.trades_var = tk.StringVar(value="0")
        self.winrate_var = tk.StringVar(value="0.0%")
        self.open_var = tk.StringVar(value="0")
        metrics = [
            ("Net equity", self.portfolio_var, "Estimated equity after modeled close costs. Not an exchange-exact liquidation balance."),
            ("Free cash", self.cash_var, "Available paper cash. Shared cross-margin backing does not guarantee protection from liquidation."),
            ("Total return", self.pnl_var, "Net equity performance versus total paper deposits, including open losses."),
            ("Open trades", self.open_var, "Currently open paper positions."),
            ("Closed trades", self.trades_var, "Closed trades in the current paper session."),
            ("Win rate", self.winrate_var, "Closed trades with positive net P&L. Open losing trades are not included."),
        ]
        self._metric_values = {}
        for i, (name, var, help_text) in enumerate(metrics):
            stats_frame.columnconfigure(i, weight=2 if i == 0 else 1, uniform="metrics")
            group = tk.Frame(stats_frame, bg=BG)
            group.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 18, 12))
            label = ttk.Label(group, text=name, foreground=MUTED, font=(FONT, 9))
            label.pack(anchor="w", pady=(0, 5))
            value = ttk.Label(group, textvariable=var, font=(FONT, 23 if i == 0 else 17, "bold"))
            value.pack(anchor="w")
            self._metric_values[name] = value
            for widget in (group, label, value):
                self._tip(widget, help_text)

        self.profit_breakdown_var = tk.StringVar(value="")
        profit_line = ttk.Label(self.root, textvariable=self.profit_breakdown_var,
                               foreground=MUTED, font=(FONT, 9), padding=(24, 0, 24, 14))
        profit_line.pack(fill="x")
        profit_line.bind("<Configure>", lambda e: profit_line.configure(wraplength=max(100, e.width - 48)))
        self._tip(profit_line, "Realized net results and estimated open P&L are separate. A high win rate can coexist with open losses. Cached marks are not guaranteed executable prices.")

        nb = ttk.Notebook(self.root)
        self.notebook = nb
        nb.pack(fill="both", expand=True)
        tabs = [tk.Frame(nb, bg=BG) for _ in range(6)]
        self.settings_tab = tabs[-1]
        for tab, name, builder in zip(tabs,
            ("Open", "Risk", "Charts", "History", "Ledger", "Settings"),
            (self._build_open_tab, self._build_risk_tab, self._build_charts_tab,
             self._build_history_tab, self._build_ledger_tab, self._build_settings_tab)):
            nb.add(tab, text=name)
            builder(tab)
        self._polish_controls(nb)
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        if not self._settings_confirmed:
            nb.select(self.settings_tab)

        footer = tk.Frame(self.root, bg=BG, padx=24, pady=10)
        footer.pack(fill="x", side="bottom")
        self.basket_var = tk.StringVar(value="Basket: waiting")
        basket_label = ttk.Label(footer, textvariable=self.basket_var,
                                foreground=MUTED, font=(FONT, 8))
        basket_label.pack(side="left", fill="x", expand=True)
        basket_label.bind("<Configure>", lambda e: basket_label.configure(wraplength=max(100, e.width)))
        ttk.Label(footer, text="FutolTech", foreground=MUTED,
                  font=(FONT, 8)).pack(side="right", padx=(16, 0))

    def _polish_controls(self, parent):
        icons = {"Refresh": "refresh", "Export Report": "download", "Export CSV": "download",
                 "Export Ops Report": "download", "Reset Futures Paper": "reset",
                 "Apply Settings": "save", "Apply Risk": "save"}
        for widget in parent.winfo_children():
            if isinstance(widget, ttk.Button):
                text = widget.cget("text")
                if text in icons:
                    widget.configure(image=self._icons[icons[text]], compound="left")
                if text in {"Apply Settings", "Apply Risk"}:
                    widget.configure(style="Primary.TButton")
                elif text in {"Reset Futures Paper", "Kill Switch"}:
                    widget.configure(style="Danger.TButton")
            self._polish_controls(widget)

    def _start_telegram_dashboard(self):
        self._telegram_commands = tg.TelegramDashboardPoller(
            futures_callback=self._telegram_futures_snapshot,
            p2p_callback=lambda: "P2P is retired from this app. Existing audit files are preserved locally.",
            info_callback=self._telegram_info_text,
            control_callback=self._telegram_control,
        )
        self._telegram_commands.start()

    def _send_telegram_menu(self):
        if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
            self.status_var.set("Telegram dashboard needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.")
            return
        tg.send_dashboard_menu("TradingBot23 dashboard controls:")
        self.status_var.set("Telegram dashboard menu sent.")

    def _telegram_futures_snapshot(self) -> str:
        now = datetime.now(timezone.utc)
        breakdown = self.trader.get_equity_breakdown(now)
        portfolio = breakdown["estimated_net_equity_usd"]
        cash = self.trader.cash_balance
        stats = self.trader.get_stats()
        initial = (
            self.trader.get_contributed_capital()
            if hasattr(self.trader, "get_contributed_capital")
            else config.CAPITAL_USD
        )
        pnl_pct = ((portfolio - initial) / initial) * 100 if initial > 0 else 0.0
        open_positions = list(self.trader.get_open_positions())
        total_pnl = breakdown["realized_net_pnl_usd"]
        last_scan = (
            self._last_cycle_time.strftime("%Y-%m-%d %H:%M:%S UTC")
            if self._last_cycle_time
            else "not run yet"
        )
        mode = "paused" if self._paused else "running"
        lines = [
            "📊 <b>TradingBot23 Futures Paper</b>",
            f"Mode: <b>{mode}</b>  |  New trades: <b>{config.LEVERAGE}x cross</b>",
            f"Net equity est.: <b>${portfolio:,.2f}</b>  |  Cash: <b>${cash:,.2f}</b>",
            f"PNL: <b>{pnl_pct:+.2f}%</b>  |  Realized: <b>${total_pnl:+,.2f}</b>",
            f"Open net est.: <b>${breakdown['unrealized_net_pnl_usd']:+,.2f}</b>",
            f"Open: <b>{len(open_positions)}</b>  |  Trades: <b>{stats.get('total_trades', 0)}</b>  |  Win: <b>{stats.get('win_rate', 0):.1f}%</b>",
            f"Last scan: {last_scan}",
        ]
        if open_positions:
            lines.append("")
            lines.append("<b>Open positions</b>")
            for pos in open_positions[:6]:
                current = pos.last_known_price or pos.entry_price
                estimate = self.trader.estimate_position_pnl(pos, now)
                lines.append(
                    f"{tg.escape_html(pos.symbol)} {pos.leverage}x | "
                    f"${pos.margin_used:,.2f} | now ${current:,.4f} | "
                    f"Net PNL {estimate['pnl_pct']:+.2f}% | liq ${pos.liquidation_price:,.4f}"
                )
            if len(open_positions) > 6:
                lines.append(f"+{len(open_positions) - 6} more open position(s)")
        return "\n".join(lines)


    def _telegram_info_text(self) -> str:
        return (
            "<b>TradingBot23 Futures Paper</b>\n"
            "Futures: paper portfolio, open positions, trade stats, and daily summary alerts.\n"
            "OKX public prices or Binance compatibility. No real-money orders.\n"
            "Commands: /dashboard, /today, /export, /info"
            + ("\nRemote pause/resume is enabled." if config.TELEGRAM_ALLOW_CONTROL else "\nRemote pause/resume is disabled by default.")
        )

    def _telegram_control(self, action: str) -> str:
        action = (action or "").lower()
        if action == "today":
            return self._telegram_today_text()
        if action in {"pause", "resume"} and not config.TELEGRAM_ALLOW_CONTROL:
            self._record_decision(
                "telegram",
                action,
                "BLOCK",
                0,
                "remote futures controls disabled",
            )
            return (
                "<b>Remote futures controls are disabled.</b>\n"
                "Telegram can still show dashboard, today, info, and export snapshots."
            )
        if action == "pause":
            self._paused = True
            self._record_decision("telegram", "pause", "BLOCK", 0, "pause requested from Telegram")
            try:
                self.root.after(0, lambda: self.pause_btn.config(text="Resume"))
            except tk.TclError:
                pass
            return "⏸️ <b>TradingBot23 paused.</b>\nExisting paper positions remain in the local ledger."
        if action == "resume":
            allowed, reasons = self._risk_allows_trading()
            if not allowed:
                self._paused = False
                self._force_event.set()
                self._record_decision("telegram", "resume", "BLOCK", 0, "; ".join(reasons))
                try:
                    self.root.after(0, lambda: self.pause_btn.config(text="Pause"))
                except tk.TclError:
                    pass
                return "⛔ <b>Resume blocked by risk guard.</b>\n" + tg.escape_html("; ".join(reasons))
            self._paused = False
            self._force_event.set()
            self._record_decision("telegram", "resume", "RUN", 100, "resume requested from Telegram")
            try:
                self.root.after(0, lambda: self.pause_btn.config(text="Pause"))
            except tk.TclError:
                pass
            return "▶️ <b>TradingBot23 resumed.</b>\nA futures paper cycle was requested."
        if action == "export":
            out = self._write_ops_report()
            self._record_decision("telegram", "export", "UPDATED", 80, out.name)
            return f"📄 <b>Operations report exported.</b>\n{tg.escape_html(str(out))}"
        return "Unknown control action."

    def _telegram_today_text(self) -> str:
        snap = self._risk_snapshot()
        allowed, reasons = self._risk_allows_trading()
        return "\n".join([
            "📅 <b>TradingBot23 Today</b>",
            f"Risk: <b>{'OK' if allowed else 'BLOCKED'}</b>",
            f"Futures daily closed P&L: <b>${snap['daily_pnl']:+,.2f}</b>",
            f"Portfolio: <b>${snap['portfolio']:,.2f}</b> | Cash: <b>${snap['cash']:,.2f}</b>",
            f"Open futures notional: <b>${snap['open_notional']:,.2f}</b>",
            f"Risk note: {tg.escape_html('; '.join(reasons) if reasons else 'limits clear')}",
        ])


    def _build_open_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=3, uniform="trade_sections")
        parent.rowconfigure(1, weight=2, uniform="trade_sections")
        open_section = tk.Frame(parent, bg=BG)
        open_section.grid(row=0, column=0, sticky="nsew")
        closed_section = tk.Frame(parent, bg=BG)
        closed_section.grid(row=1, column=0, sticky="nsew")
        # Open positions
        pl = tk.Frame(open_section, bg="#111214")
        pl.pack(fill="x", padx=15, pady=(10, 2))
        ttk.Label(pl, text="Open positions", style="Header.TLabel").pack(side="left")
        self._positions_count = tk.StringVar(value=f"0 / {config.MAX_OPEN_TRADES}")
        ttk.Label(pl, textvariable=self._positions_count, foreground=MUTED).pack(side="right")

        pf = tk.Frame(open_section, bg="#111214")
        pf.pack(fill="both", expand=True, padx=15)

        pos_cols = ("symbol","amount","lev","entry","current","pnl","trigger","tp","sl","age")
        self.pos_tree = ttk.Treeview(pf, columns=pos_cols, show="headings", height=5)
        pnl_heading = "Net P&L / Price move"
        risk_heading = "Cross liq. est."
        for col, heading, width in [
            ("symbol","Symbol",75),("amount","Margin $",98),("lev","Entry lev.",86),
            ("entry","Entry",94),("current","Mark",94),
            ("pnl",pnl_heading,178),("trigger","24h trigger",96),
            ("tp","Net TP",94),("sl",risk_heading,108),("age","Age",64),
        ]:
            self.pos_tree.heading(col, text=heading)
            self.pos_tree.column(col, width=width, minwidth=width, anchor="center")
        self._mount_trade_table(self.pos_tree, pf)
        self._open_empty = ttk.Label(pf, text="No open positions", foreground=MUTED,
                                     background="#191c1f", padding=10)

        # Closed trades
        cl = tk.Frame(closed_section, bg="#111214")
        cl.pack(fill="x", padx=15, pady=(10, 2))
        ttk.Label(cl, text="Recent closed trades", style="Header.TLabel").pack(anchor="w")

        cf = tk.Frame(closed_section, bg="#111214")
        cf.pack(fill="both", expand=True, padx=15, pady=(0, 8))

        closed_cols = ("symbol","amount","lev","entry","exit","pnl","pnl_usd","trigger","reason","time")
        self.closed_tree = ttk.Treeview(cf, columns=closed_cols, show="headings", height=5)
        for col, heading, width in [
            ("symbol","Symbol",75),("amount","Margin $",98),("lev","Entry lev.",86),
            ("entry","Entry",94),("exit","Exit",94),
            ("pnl","Net P&L %",94),("pnl_usd","Net P&L $",94),
            ("trigger","24h trigger",96),("reason","Reason",112),("time","Closed",108),
        ]:
            self.closed_tree.heading(col, text=heading)
            self.closed_tree.column(col, width=width, minwidth=width, anchor="center")
        self._mount_trade_table(self.closed_tree, cf)

    @staticmethod
    def _mount_trade_table(tree, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        vertical = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.tag_configure("even", background="#191c1f")
        tree.tag_configure("odd", background="#1d2023")

    # ── Professional risk cockpit ─────────────────────────────────────────────

    def _build_risk_tab(self, parent):
        body = tk.Frame(parent, bg="#111214", padx=15, pady=12)
        body.pack(fill="both", expand=True)

        top = tk.Frame(body, bg="#111214")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Risk controls", style="Header.TLabel",
                  background="#111214").pack(side="left")
        risk_refresh_btn = ttk.Button(top, text="Refresh", style="Btn.TButton",
                                      command=self._refresh_risk_tab)
        risk_refresh_btn.pack(side="right")
        self._tip(risk_refresh_btn, "Refresh the risk metrics, control state, and decision log.")
        export_btn = ttk.Button(top, text="Export Ops Report", style="Btn.TButton",
                                command=self._export_ops_report)
        export_btn.pack(side="right", padx=(0, 6))
        self._tip(export_btn, "Write a local operations report with futures, risk, and decision-log snapshots.")
        rebound_btn = ttk.Button(top, text="Run 5Y Rebound", style="Btn.TButton",
                                 command=self._run_rebound_study)
        rebound_btn.pack(side="right", padx=(0, 6))
        self._tip(rebound_btn, "Run the historical rebound-duration study for the top-50 universe in the background.")

        self._risk_summary_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self._risk_summary_var,
                  foreground="#a0aab2", background="#111214",
                  font=(FONT, 9)).pack(fill="x", anchor="w", pady=(0, 8))

        controls = tk.Frame(body, bg="#111214")
        controls.pack(fill="x", pady=(0, 10))

        self._risk_profile = tk.StringVar(value=config.BOT_PROFILE)
        self._risk_max_daily_loss = tk.StringVar(value=str(config.RISK_MAX_DAILY_LOSS_USD))
        self._risk_max_exposure = tk.StringVar(value=str(config.RISK_MAX_OPEN_EXPOSURE_USD))
        self._risk_max_loss_streak = tk.StringVar(value=str(config.RISK_MAX_LOSS_STREAK))

        def entry(parent_frame, var, width):
            return tk.Entry(
                parent_frame,
                textvariable=var,
                width=width,
                font=(FONT, 9),
                bg="#f5f7f8",
                fg="#111214",
                insertbackground="#111214",
                selectbackground="#59dcb2",
                selectforeground="#111214",
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground="#343b40",
                highlightcolor="#59dcb2",
            )

        for label_text, var, width in [
            ("Profile", self._risk_profile, 12),
            ("Max daily loss $", self._risk_max_daily_loss, 8),
            ("Max open notional $", self._risk_max_exposure, 9),
            ("Max loss streak", self._risk_max_loss_streak, 5),
        ]:
            group = tk.Frame(controls, bg="#111214")
            group.pack(side="left", padx=(0, 10))
            label = ttk.Label(group, text=label_text, foreground="#a0aab2", background="#111214",
                              font=(FONT, 8))
            label.pack(anchor="w")
            input_widget = entry(group, var, width)
            input_widget.pack(anchor="w")
            help_text = RISK_HELP.get(label_text, "")
            self._tip(label, help_text)
            self._tip(input_widget, help_text)

        btns = tk.Frame(body, bg="#111214")
        btns.pack(fill="x", pady=(0, 10))
        apply_risk_btn = ttk.Button(btns, text="Apply Risk", style="Btn.TButton",
                                    command=self._apply_risk_settings)
        apply_risk_btn.pack(side="left", padx=(0, 6))
        self._tip(apply_risk_btn, "Save and apply risk settings. Profile changes require restart because they change the data folder.")
        kill_btn = ttk.Button(btns, text="Kill Switch", style="Btn.TButton",
                              command=self._risk_kill)
        kill_btn.pack(side="left", padx=(0, 6))
        self._tip(kill_btn, "Immediately block new futures entries. Existing positions are still monitored for exits.")
        clear_kill_btn = ttk.Button(btns, text="Clear Kill", style="Btn.TButton",
                                    command=self._risk_clear_kill)
        clear_kill_btn.pack(side="left", padx=(0, 6))
        self._tip(clear_kill_btn, "Clear the manual kill switch. Other risk guards may still block trading.")
        resume_allowed_btn = ttk.Button(btns, text="Resume If Allowed", style="Btn.TButton",
                                        command=self._risk_resume)
        resume_allowed_btn.pack(side="left", padx=(0, 6))
        self._tip(resume_allowed_btn, "Resume futures scanning only if all configured risk guards pass.")
        self._risk_action_var = tk.StringVar(value="")
        ttk.Label(btns, textvariable=self._risk_action_var,
                  foreground="#47c997", background="#111214",
                  font=(FONT, 9)).pack(side="left", padx=10)

        panes = tk.PanedWindow(body, orient=tk.VERTICAL, sashwidth=4, bg="#111214")
        self._risk_panes = panes
        panes.pack(fill="both", expand=True)

        risk_frame = tk.Frame(panes, bg="#111214")
        panes.add(risk_frame, minsize=155)
        ttk.Label(risk_frame, text="Account risk", style="Header.TLabel",
                  background="#111214").pack(anchor="w", pady=(0, 3))
        cols = ("metric", "value", "limit", "status")
        risk_table = tk.Frame(risk_frame, bg="#111214")
        risk_table.pack(fill="both", expand=True)
        self.risk_tree = ttk.Treeview(risk_table, columns=cols, show="headings", height=7)
        for col, heading, width in [
            ("metric", "METRIC", 210),
            ("value", "VALUE", 220),
            ("limit", "LIMIT", 180),
            ("status", "STATUS", 180),
        ]:
            self.risk_tree.heading(col, text=heading)
            self.risk_tree.column(col, width=width, anchor="center")
        self.risk_tree.tag_configure("ok", foreground="#47c997")
        self.risk_tree.tag_configure("warn", foreground="#e9bc67")
        self.risk_tree.tag_configure("block", foreground="#ff777d")
        risk_vsb = ttk.Scrollbar(risk_table, orient="vertical", command=self.risk_tree.yview)
        self.risk_tree.configure(yscrollcommand=risk_vsb.set)
        self.risk_tree.pack(side="left", fill="both", expand=True)
        risk_vsb.pack(side="right", fill="y")

        decision_frame = tk.Frame(panes, bg="#111214")
        panes.add(decision_frame, minsize=115)
        ttk.Label(decision_frame, text="Entry decisions", style="Header.TLabel",
                  background="#111214").pack(anchor="w", pady=(8, 3))
        dcols = ("time", "domain", "action", "decision", "score", "reason")
        decision_table = tk.Frame(decision_frame, bg="#111214")
        decision_table.pack(fill="both", expand=True)
        self.decision_tree = ttk.Treeview(decision_table, columns=dcols, show="headings", height=5)
        for col, heading, width in [
            ("time", "TIME", 125),
            ("domain", "DOMAIN", 85),
            ("action", "ACTION", 125),
            ("decision", "DECISION", 95),
            ("score", "SCORE", 65),
            ("reason", "REASON", 520),
        ]:
            self.decision_tree.heading(col, text=heading)
            self.decision_tree.column(col, width=width, anchor="center")
        self.decision_tree.tag_configure("go", foreground="#47c997")
        self.decision_tree.tag_configure("wait", foreground="#e9bc67")
        self.decision_tree.tag_configure("block", foreground="#ff777d")
        decision_vsb = ttk.Scrollbar(decision_table, orient="vertical", command=self.decision_tree.yview)
        self.decision_tree.configure(yscrollcommand=decision_vsb.set)
        self.decision_tree.pack(side="left", fill="both", expand=True)
        decision_vsb.pack(side="right", fill="y")
        self._refresh_risk_tab()
        self.root.after(150, self._fit_risk_panes)

    def _build_charts_tab(self, parent):
        ctrl = tk.Frame(parent, bg="#111214", pady=8)
        ctrl.pack(fill="x", padx=15)
        ttk.Button(ctrl, text="Refresh Charts", style="Btn.TButton",
                   command=self._draw_charts).pack(side="left")
        ttk.Label(ctrl, text="  Updates automatically when you switch to this tab.",
                  foreground="#a0aab2", background="#111214",
                  font=(FONT, 9)).pack(side="left")

        self._chart_frame = tk.Frame(parent, bg="#111214")
        self._chart_frame.pack(fill="both", expand=True)
        self._canvas_widget = None

        # Placeholder until first draw
        ttk.Label(self._chart_frame,
                  text="Switch to Charts tab after the bot runs a few trades.",
                  foreground="#a0aab2", background="#111214",
                  font=(FONT, 10)).pack(expand=True)

    # ── Chart rendering ────────────────────────────────────────────────────────

    def _draw_charts(self):
        # Clear old chart
        for w in self._chart_frame.winfo_children():
            w.destroy()

        closed = self.trader.get_trade_history()
        with self._equity_lock:
            eq_hist = list(self._equity_history)

        plt.style.use("dark_background")
        fig = plt.figure(figsize=(11, 7), facecolor="#111214")
        gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.5, wspace=0.4)

        # ── 1. Equity curve ──
        ax1 = fig.add_subplot(gs[0, :])
        ax1.set_facecolor("#191c1f")
        if len(eq_hist) >= 2:
            xs = [e[0] for e in eq_hist]
            ys = [e[1] for e in eq_hist]
            ax1.plot(xs, ys, color="#59dcb2", linewidth=2)
            ax1.fill_between(xs, config.CAPITAL_USD, ys,
                             where=[v >= config.CAPITAL_USD for v in ys],
                             alpha=0.15, color="#47c997")
            ax1.fill_between(xs, config.CAPITAL_USD, ys,
                             where=[v < config.CAPITAL_USD for v in ys],
                             alpha=0.15, color="#ff777d")
            ax1.axhline(config.CAPITAL_USD, color="#a0aab2",
                        linestyle="--", linewidth=0.8, alpha=0.6)
            final  = ys[-1]
            change = (final - config.CAPITAL_USD) / config.CAPITAL_USD * 100
            ax1.set_title(f"Equity Curve  |  ${config.CAPITAL_USD:.0f} -> ${final:.2f} ({change:+.2f}%)",
                          color="#edf1f4", fontsize=10)
        else:
            ax1.set_title("Equity Curve  (collecting data...)", color="#edf1f4", fontsize=10)
            ax1.text(0.5, 0.5, "Not enough data yet", transform=ax1.transAxes,
                     ha="center", va="center", color="#a0aab2", fontsize=11)
        ax1.tick_params(colors="#a0aab2", labelsize=7)
        ax1.set_ylabel("Portfolio $", color="#a0aab2", fontsize=8)
        for sp in ax1.spines.values(): sp.set_edgecolor("#343b40")

        # ── 2. P&L distribution ──
        ax2 = fig.add_subplot(gs[1, 0])
        ax2.set_facecolor("#191c1f")
        if closed:
            pnls = [t.pnl_pct for t in closed]
            ax2.hist(pnls, bins=max(10, len(pnls)//3), color="#59dcb2",
                     alpha=0.75, edgecolor="#111214", linewidth=0.3)
            ax2.axvline(0, color="#ff777d", linewidth=1.2, linestyle="--")
            ax2.axvline(np.mean(pnls), color="#47c997", linewidth=1.2, linestyle="--",
                        label=f"Mean {np.mean(pnls):+.2f}%")
            ax2.legend(fontsize=7, labelcolor="#edf1f4", facecolor="#24282c")
        ax2.set_title("Trade Returns", color="#edf1f4", fontsize=9)
        ax2.set_xlabel("P&L %", color="#a0aab2", fontsize=8)
        ax2.tick_params(colors="#a0aab2", labelsize=7)
        for sp in ax2.spines.values(): sp.set_edgecolor("#343b40")

        # ── 3. Exit breakdown pie ──
        ax3 = fig.add_subplot(gs[1, 1])
        ax3.set_facecolor("#191c1f")
        if closed:
            reasons = defaultdict(int)
            for t in closed:
                r = t.status.value if hasattr(t.status, "value") else str(t.status)
                reasons[r] += 1
            labels = list(reasons.keys())
            sizes  = list(reasons.values())
            colors = {"tp_hit":"#47c997","sl_hit":"#ff777d","crash_sl":"#f0883e",
                      "expired":"#e9bc67","liquidated":"#ff6b6b",
                      "month_end":"#a0aab2"}
            clrs = [colors.get(l, "#59dcb2") for l in labels]
            wedges, texts, autotexts = ax3.pie(
                sizes, labels=labels, autopct="%1.0f%%",
                colors=clrs, startangle=90,
                textprops={"color":"#edf1f4","fontsize":7},
            )
            for at in autotexts:
                at.set_color("#111214"); at.set_fontsize(7); at.set_fontweight("bold")
        else:
            ax3.text(0.5, 0.5, "No trades yet", transform=ax3.transAxes,
                     ha="center", va="center", color="#a0aab2")
        ax3.set_title("Exit Breakdown", color="#edf1f4", fontsize=9)

        # ── 4. Cumulative P&L per trade ──
        ax4 = fig.add_subplot(gs[1, 2])
        ax4.set_facecolor("#191c1f")
        if closed:
            cum = np.cumsum([t.pnl_usd for t in closed])
            colors_bar = ["#47c997" if v >= 0 else "#ff777d" for v in cum]
            ax4.bar(range(len(cum)), cum, color=colors_bar, alpha=0.8, width=0.8)
            ax4.axhline(0, color="#a0aab2", linewidth=0.8)
            ax4.set_title(f"Cumulative P&L  ({cum[-1]:+.2f} USD)", color="#edf1f4", fontsize=9)
            ax4.set_xlabel("Trade #", color="#a0aab2", fontsize=8)
            ax4.set_ylabel("USD", color="#a0aab2", fontsize=8)
        else:
            ax4.set_title("Cumulative P&L", color="#edf1f4", fontsize=9)
            ax4.text(0.5, 0.5, "No trades yet", transform=ax4.transAxes,
                     ha="center", va="center", color="#a0aab2")
        ax4.tick_params(colors="#a0aab2", labelsize=7)
        for sp in ax4.spines.values(): sp.set_edgecolor("#343b40")

        # Footer stats
        if closed:
            wins = [t for t in closed if t.pnl_pct > 0]
            wr   = len(wins) / len(closed) * 100
            ev   = np.mean([t.pnl_pct for t in closed])
            fig.text(0.01, 0.002,
                f"Trades: {len(closed)}  |  Win rate: {wr:.1f}%  |  "
                f"Avg P&L: {ev:+.3f}%  |  "
                f"Best: {max(t.pnl_pct for t in closed):+.2f}%  |  "
                f"Worst: {min(t.pnl_pct for t in closed):+.2f}%",
                color="#a0aab2", fontsize=7.5)

        fig.patch.set_facecolor("#111214")

        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas_widget = canvas
        plt.close(fig)

    # ── History tab ───────────────────────────────────────────────────────────

    def _build_history_tab(self, parent):
        ctrl = tk.Frame(parent, bg="#111214", pady=8)
        ctrl.pack(fill="x", padx=15)
        ttk.Button(ctrl, text="Refresh", style="Btn.TButton",
                   command=self._refresh_history).pack(side="left")
        ttk.Button(ctrl, text="Export Report", style="Btn.TButton",
                   command=self._export_history_report).pack(side="left", padx=(6, 0))
        ttk.Button(ctrl, text="Reset Futures Paper", style="Btn.TButton",
                   command=self._reset_futures_paper).pack(side="left", padx=(6, 0))
        self._hist_summary_var = tk.StringVar(value="")
        summary_label = ttk.Label(parent, textvariable=self._hist_summary_var, foreground="#a0aab2",
                                  background="#111214", font=(FONT, 9), wraplength=950)
        summary_label.pack(fill="x", padx=15, pady=(0, 4))
        summary_label.bind("<Configure>", lambda e: summary_label.configure(wraplength=max(250, e.width)))
        self._hist_metrics_var = tk.StringVar(value="")
        metrics_label = ttk.Label(parent, textvariable=self._hist_metrics_var,
                                  foreground="#f5f7f8", background="#111214",
                                  font=(FONT, 10), wraplength=950)
        metrics_label.pack(fill="x", padx=15, pady=(0, 8))
        metrics_label.bind("<Configure>", lambda e: metrics_label.configure(wraplength=max(250, e.width)))
        self._tip(metrics_label, "Closed-trade net results including modeled fees and funding. Profit factor is total winning dollars divided by total losing dollars; above 1 is positive realized performance. Expectancy is average net dollars per closed trade. Open losses are not included.")

        hf = tk.Frame(parent, bg="#111214")
        hf.pack(fill="both", expand=True, padx=15, pady=(0, 8))

        hist_cols = ("date","symbol","engine","entry","exit","amount","lev","pnl_pct","pnl_usd","reason","trigger")
        self.hist_tree = ttk.Treeview(hf, columns=hist_cols, show="headings")
        for col, heading, width in [
            ("date","CLOSED",110),("symbol","SYMBOL",65),("engine","ENGINE",60),
            ("entry","ENTRY",85),("exit","EXIT",85),("amount","AMOUNT $",80),
            ("lev","ENTRY LEV",70),("pnl_pct","P&L %",65),("pnl_usd","P&L $",75),
            ("reason","REASON",75),("trigger","24H TRIG",75),
        ]:
            self.hist_tree.heading(col, text=heading)
            self.hist_tree.column(col, width=width, anchor="center")

        vsb = ttk.Scrollbar(hf, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=vsb.set)
        self.hist_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.hist_tree.tag_configure("win",  foreground="#47c997")
        self.hist_tree.tag_configure("loss", foreground="#ff777d")

    def _futures_history_session_note(self) -> str:
        sessions = recent_reset_sessions(limit=1)
        if not sessions:
            return ""
        last = sessions[-1]
        reset_time = last.get("reset_time", "")[:16].replace("T", " ")
        archived_trades = int(self._num(last.get("archived_closed_trades")))
        archived_open = int(self._num(last.get("archived_open_positions")))
        return (
            f"  |  Current session since {reset_time} UTC"
            f"  |  archived {archived_trades} trades/{archived_open} open"
        )

    def _refresh_history(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)

        path = _history_csv()
        stats = self.trader.get_stats()
        pf = stats.get("profit_factor")
        pf_text = f"{pf:.2f}" if pf is not None else "N/A (no losses)"
        self._hist_metrics_var.set(
            f"Profit factor: {pf_text}  |  Expectancy: ${stats['expectancy_usd']:+.2f}/trade  |  "
            f"Avg win: ${stats['avg_win_usd']:.2f}  |  Avg loss: ${stats['avg_loss_usd']:.2f}")
        if not path.exists():
            note = self._futures_history_session_note()
            self._hist_summary_var.set("No current-session trade history yet." + note)
            return

        rows = []
        with open(path, "r", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))

        total = len(rows)
        wins  = sum(1 for r in rows if float(r.get("pnl_pct", 0)) > 0)
        total_pnl = sum(float(r.get("pnl_usd", 0)) for r in rows)
        wr = (wins / total * 100) if total else 0
        self._hist_summary_var.set(
            f"  {total} trades  |  Win rate: {wr:.1f}%  |  Total P&L: ${total_pnl:+.2f}"
            f"{self._futures_history_session_note()}")

        for r in reversed(rows):
            pnl = float(r.get("pnl_pct", 0))
            tag = "win" if pnl > 0 else "loss"
            close_t = r.get("close_time", "")[:16].replace("T", " ")
            self.hist_tree.insert("", "end", tags=(tag,), values=(
                close_t,
                r.get("symbol",""),
                r.get("engine",""),
                f"${float(r.get('entry_price',0)):.4f}",
                f"${float(r.get('exit_price',0)):.4f}" if r.get("exit_price") else "--",
                f"${float(r.get('amount_usd',0)):.2f}",
                f"{r.get('leverage','1')}x",
                f"{pnl:+.2f}%",
                f"${float(r.get('pnl_usd',0)):+.2f}",
                r.get("reason",""),
                f"{float(r.get('entry_change_24h',0)):+.2f}%",
            ))

    def _reset_futures_paper(self):
        open_count = len(self.trader.get_open_positions())
        closed_count = len(self.trader.get_trade_history())
        msg = (
            "Archive the current futures paper session and start a fresh one?\n\n"
            f"Closed trades to archive: {closed_count}\n"
            f"Open positions to archive/clear: {open_count}\n\n"
            "P2P paper data will not be changed. Futures will be paused after reset."
        )
        if not messagebox.askyesno("Reset Futures Paper", msg, parent=self.root):
            return

        self._paused = True
        self.pause_btn.config(text="Resume")
        self._force_event.clear()
        self._write_env({"AUTO_START_FUTURES": "false"})
        config.AUTO_START_FUTURES = False
        if not self._account_lock.acquire(blocking=False):
            self.status_var.set("Current scan is finishing. Reset again after it finishes.")
            return
        try:
            summary = self.trader.reset_paper_account(reason="dashboard_reset")
        except Exception as exc:
            logger.exception("Failed to reset futures paper account")
            self.status_var.set(f"Futures reset failed: {exc}")
            return
        finally:
            self._account_lock.release()

        with self._equity_lock:
            self._equity_history.clear()
        self._last_cycle_time = None
        self._last_cycle_summary = {}
        self._next_cycle_ts = 0.0
        self._record_decision(
            "futures",
            "paper_reset",
            "UPDATED",
            100,
            f"archived to {summary['session_id']}",
        )
        self.status_var.set(
            f"Futures paper reset. Archived to {summary['session_id']}; trading is paused."
        )
        self._refresh_history()
        self._update_stats()
        self._update_positions()
        self._update_closed()
        if hasattr(self, "ledger_tree"):
            self._refresh_event_ledger()

    def _export_history_report(self):
        path = _history_csv()
        if not path.exists():
            self._hist_summary_var.set("No trade history to export.")
            return

        with open(path, "r", encoding="utf-8") as f:
            rows = list(_csv.DictReader(f))
        if not rows:
            self._hist_summary_var.set("No trade history to export.")
            return

        total = len(rows)
        wins = [r for r in rows if self._num(r.get("pnl_pct")) > 0]
        losses = [r for r in rows if self._num(r.get("pnl_pct")) <= 0]
        total_pnl_usd = sum(self._num(r.get("pnl_usd")) for r in rows)
        avg_pnl_pct = sum(self._num(r.get("pnl_pct")) for r in rows) / total
        best = max(rows, key=lambda r: self._num(r.get("pnl_pct")))
        worst = min(rows, key=lambda r: self._num(r.get("pnl_pct")))
        contributed_capital = (
            self.trader.get_contributed_capital()
            if hasattr(self.trader, "get_contributed_capital")
            else config.CAPITAL_USD
        )
        portfolio = self.trader.get_portfolio_value()

        by_engine = defaultdict(list)
        by_reason = defaultdict(list)
        by_leverage = defaultdict(list)
        for row in rows:
            by_engine[row.get("engine", "unknown")].append(row)
            by_reason[row.get("reason", "unknown")].append(row)
            by_leverage[row.get("leverage", "1")].append(row)

        def section(title, groups):
            lines = [title]
            for key in sorted(groups):
                group = groups[key]
                group_wins = sum(1 for r in group if self._num(r.get("pnl_pct")) > 0)
                group_pnl = sum(self._num(r.get("pnl_usd")) for r in group)
                win_rate = group_wins / len(group) * 100 if group else 0
                lines.append(
                    f"  {key}: {len(group)} trades | win rate {win_rate:.1f}% | P&L ${group_pnl:+.2f}"
                )
            return "\n".join(lines)

        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        report = "\n\n".join([
            "TradingBot23 Performance Report",
            f"Generated: {generated}",
            (
                f"Trades: {total}\n"
                f"Wins: {len(wins)} | Losses/breakeven: {len(losses)} | "
                f"Win rate: {(len(wins) / total * 100):.1f}%\n"
                f"Contributed capital: ${contributed_capital:,.2f}\n"
                f"Current portfolio: ${portfolio:,.2f}\n"
                f"Total P&L: ${total_pnl_usd:+.2f}\n"
                f"Average P&L per trade: {avg_pnl_pct:+.2f}%\n"
                f"Best trade: {best.get('symbol', '')} {self._num(best.get('pnl_pct')):+.2f}% "
                f"(${self._num(best.get('pnl_usd')):+.2f})\n"
                f"Worst trade: {worst.get('symbol', '')} {self._num(worst.get('pnl_pct')):+.2f}% "
                f"(${self._num(worst.get('pnl_usd')):+.2f})"
            ),
            section("By Engine", by_engine),
            section("By Entry Leverage", by_leverage),
            section("By Exit Reason", by_reason),
            "Note: This report summarizes local paper futures history from trade_history.csv.",
        ])

        out = config.DATA_DIR / f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out.write_text(report, encoding="utf-8")
        self._hist_summary_var.set(f"Report exported: {out.name}")

    # ── Event ledger tab ─────────────────────────────────────────────────────

    def _build_ledger_tab(self, parent):
        body = tk.Frame(parent, bg="#111214", padx=15, pady=12)
        body.pack(fill="both", expand=True)

        top = tk.Frame(body, bg="#111214")
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="UNIFIED EVENT LEDGER", style="Header.TLabel",
                  background="#111214").pack(side="left")
        ttk.Button(top, text="Refresh", style="Btn.TButton",
                   command=self._refresh_event_ledger).pack(side="right")

        self._ledger_summary_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self._ledger_summary_var,
                  foreground="#a0aab2", background="#111214",
                  font=(FONT, 9)).pack(fill="x", anchor="w", pady=(0, 8))

        cols = ("time", "domain", "type", "status", "amount", "pnl", "balance", "symbol", "details")
        self.ledger_tree = ttk.Treeview(body, columns=cols, show="headings", height=22)
        for col, heading, width in [
            ("time", "TIME", 135),
            ("domain", "DOMAIN", 80),
            ("type", "TYPE", 120),
            ("status", "STATUS", 100),
            ("amount", "AMOUNT", 110),
            ("pnl", "P&L", 95),
            ("balance", "BALANCE", 115),
            ("symbol", "SYMBOL/ROUTE", 115),
            ("details", "DETAILS", 420),
        ]:
            self.ledger_tree.heading(col, text=heading)
            self.ledger_tree.column(col, width=width, anchor="center")
        self.ledger_tree.tag_configure("profit", foreground="#47c997")
        self.ledger_tree.tag_configure("loss", foreground="#ff777d")
        self.ledger_tree.tag_configure("system", foreground="#e9bc67")
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.ledger_tree.yview)
        self.ledger_tree.configure(yscrollcommand=vsb.set)
        self.ledger_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._refresh_event_ledger()



    @staticmethod
    def _format_rate(rate: float | None) -> str:
        if rate is None:
            return "--"
        pct = rate * 100 if rate <= 1 else rate
        return f"{pct:.1f}%"

    @staticmethod
    def _clip_text(value: str, limit: int) -> str:
        text = str(value or "")
        return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."

    @staticmethod
    def _price_text(value) -> str:
        if value is None or not math.isfinite(value):
            return "--"
        decimals = 8 if 0 < abs(value) < 0.01 else 4
        return f"${value:,.{decimals}f}"

    # ── Settings tab ──────────────────────────────────────────────────────────

    def _build_settings_tab(self, parent):
        canvas = tk.Canvas(parent, bg="#111214", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        body = tk.Frame(canvas, bg="#111214", padx=15, pady=14)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_window, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"))

        settings_panel = tk.Frame(body, bg="#111214")
        settings_panel.pack(side="left", fill="y", anchor="nw")

        ttk.Label(settings_panel, text="Trading parameters", style="Header.TLabel",
                  background="#111214").pack(anchor="w", pady=(0, 4))

        grid = tk.Frame(settings_panel, bg="#111214")
        grid.pack(fill="x")

        def field(parent, var, width):
            return tk.Entry(
                parent,
                textvariable=var,
                width=width,
                font=(FONT, 10),
                bg="#f5f7f8",
                fg="#111214",
                insertbackground="#111214",
                selectbackground="#59dcb2",
                selectforeground="#111214",
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground="#343b40",
                highlightcolor="#59dcb2",
            )

        def row(label, widget_factory, r):
            label_widget = ttk.Label(grid, text=label, foreground="#a0aab2", background="#111214",
                                     font=(FONT, 9), width=22)
            label_widget.grid(row=r, column=0, sticky="w", pady=4)
            w = widget_factory(grid)
            w.grid(row=r, column=1, sticky="w", padx=8, pady=6, ipady=4)
            help_text = SETTINGS_HELP.get(label, "")
            self._tip(label_widget, help_text)
            self._tip(w, help_text)
            return w

        # Capital
        self._s_capital = tk.StringVar(value=str(int(config.CAPITAL_USD)))
        row("Capital (USD)", lambda p: field(p, self._s_capital, 10), 0)

        # Leverage
        self._s_leverage = tk.IntVar(value=config.LEVERAGE)
        lev_frame = tk.Frame(grid, bg="#111214")
        lev_frame.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        lev_label = ttk.Label(grid, text="Leverage", foreground="#a0aab2", background="#111214",
                              font=(FONT, 9), width=22)
        lev_label.grid(row=1, column=0, sticky="w", pady=4)
        lev_spin = tk.Spinbox(
            lev_frame,
            from_=1,
            to=config.MAX_LEVERAGE,
            textvariable=self._s_leverage,
            width=5,
            font=(FONT, 10),
            bg="#f5f7f8",
            fg="#111214",
            buttonbackground="#edf1f4",
            insertbackground="#111214",
            selectbackground="#59dcb2",
            selectforeground="#111214",
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#343b40",
            highlightcolor="#59dcb2",
        )
        lev_spin.pack(side="left", ipady=4)
        ttk.Label(lev_frame, text="x", foreground="#a0aab2", background="#111214",
                  font=(FONT, 9)).pack(side="left", padx=(6, 0))
        self._tip(lev_label, SETTINGS_HELP["Leverage"])
        self._tip(lev_spin, SETTINGS_HELP["Leverage"])

        # TP %
        self._s_tp = tk.StringVar(value=str(round(config.FUTURES_NET_TP_PCT * 100, 2)))
        row("TP target (% net)", lambda p: field(p, self._s_tp, 8), 2)

        # SL enable + %
        self._s_sl_enabled = tk.BooleanVar(value=config.FUTURES_USE_SL)
        self._s_sl = tk.StringVar(value=str(round(config.FUTURES_NET_SL_PCT * 100, 2)))
        sl_frame = tk.Frame(grid, bg="#111214")
        sl_frame.grid(row=3, column=1, sticky="w", padx=8, pady=4)
        sl_label = ttk.Label(grid, text="Stop Loss", foreground="#a0aab2", background="#111214",
                             font=(FONT, 9), width=22)
        sl_label.grid(row=3, column=0, sticky="w", pady=4)
        sl_check = ttk.Checkbutton(sl_frame, text="Enable", variable=self._s_sl_enabled)
        sl_check.pack(side="left")
        sl_input = field(sl_frame, self._s_sl, 8)
        sl_input.pack(side="left", padx=8, ipady=4)
        ttk.Label(sl_frame, text="% net", foreground="#a0aab2", background="#111214",
                  font=(FONT,9)).pack(side="left")
        self._tip(sl_label, SETTINGS_HELP["Stop Loss"])
        self._tip(sl_check, SETTINGS_HELP["Stop Loss"])
        self._tip(sl_input, SETTINGS_HELP["Stop Loss"])

        # Crash protection
        self._s_crash_entry_guard = tk.BooleanVar(value=config.CRASH_ENTRY_GUARD_ENABLED)
        self._s_crash_emergency_sl = tk.BooleanVar(value=config.CRASH_EMERGENCY_SL_ENABLED)
        crash_frame = tk.Frame(grid, bg="#111214")
        crash_frame.grid(row=4, column=1, sticky="w", padx=8, pady=4)
        crash_label = ttk.Label(grid, text="Crash protection", foreground="#a0aab2", background="#111214",
                                font=(FONT, 9), width=22)
        crash_label.grid(row=4, column=0, sticky="w", pady=4)
        crash_entry_check = ttk.Checkbutton(
            crash_frame,
            text="Block entries",
            variable=self._s_crash_entry_guard,
        )
        crash_entry_check.pack(side="left")
        crash_sl_check = ttk.Checkbutton(
            crash_frame,
            text="Emergency SL",
            variable=self._s_crash_emergency_sl,
        )
        crash_sl_check.pack(side="left", padx=(12, 0))
        self._tip(crash_label, SETTINGS_HELP["Crash protection"])
        self._tip(crash_entry_check, "Pauses new futures entries while BTC 24h change is below the crash threshold. Existing positions are not closed by this setting.")
        self._tip(crash_sl_check, "Optional anti-crash stop. When enabled, crash mode sets an emergency SL on existing open positions; this behaves like an SL.")

        # BTC market-regime filter
        btc_filter_value = (
            ""
            if config.BTC_REGIME_FILTER_PCT is None
            else str(round(config.BTC_REGIME_FILTER_PCT * 100, 2))
        )
        self._s_btc_regime_filter = tk.StringVar(value=btc_filter_value)
        row("BTC filter (% 1h)", lambda p: field(p, self._s_btc_regime_filter, 8), 5)

        # Max hold days
        self._s_hold = tk.StringVar(value=str(config.MAX_HOLD_DAYS))
        row("Max hold (days)", lambda p: field(p, self._s_hold, 8), 6)

        # Per trade %
        self._s_per_trade = tk.StringVar(value=str(round(config.PER_TRADE_PCT * 100, 0)))
        row("Per trade (% of portfolio)", lambda p: field(p, self._s_per_trade, 8), 7)

        # Maximum simultaneous futures trades
        self._s_max_open_trades = tk.IntVar(value=config.MAX_OPEN_TRADES)
        max_open_frame = tk.Frame(grid, bg="#111214")
        max_open_frame.grid(row=8, column=1, sticky="w", padx=8, pady=4)
        max_open_label = ttk.Label(grid, text="Max open trades", foreground="#a0aab2", background="#111214",
                                   font=(FONT, 9), width=22)
        max_open_label.grid(row=8, column=0, sticky="w", pady=4)
        max_open_spin = tk.Spinbox(
            max_open_frame,
            from_=1,
            to=config.MAX_OPEN_TRADES_CAP,
            textvariable=self._s_max_open_trades,
            width=5,
            font=(FONT, 10),
            bg="#f5f7f8",
            fg="#111214",
            buttonbackground="#edf1f4",
            insertbackground="#111214",
            selectbackground="#59dcb2",
            selectforeground="#111214",
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightbackground="#343b40",
            highlightcolor="#59dcb2",
        )
        max_open_spin.pack(side="left", ipady=4)
        ttk.Label(max_open_frame, text=f"1-{config.MAX_OPEN_TRADES_CAP}",
                  foreground="#a0aab2", background="#111214",
                  font=(FONT, 9)).pack(side="left", padx=(6, 0))
        self._tip(max_open_label, SETTINGS_HELP["Max open trades"])
        self._tip(max_open_spin, SETTINGS_HELP["Max open trades"])

        # Pre-trade wave analysis
        self._s_pretrade_enabled = tk.BooleanVar(value=config.PRE_TRADE_ANALYSIS_ENABLED)
        pretrade_frame = tk.Frame(grid, bg="#111214")
        pretrade_frame.grid(row=9, column=1, sticky="w", padx=8, pady=4)
        pretrade_label = ttk.Label(grid, text="Pre-trade wave check", foreground="#a0aab2", background="#111214",
                                   font=(FONT, 9), width=22)
        pretrade_label.grid(row=9, column=0, sticky="w", pady=4)
        pretrade_check = ttk.Checkbutton(pretrade_frame, text="Enable", variable=self._s_pretrade_enabled)
        pretrade_check.pack(side="left")
        self._s_confirm_rebound = tk.BooleanVar(value=config.PRE_TRADE_CONFIRMATION_ENABLED)
        confirm_check = ttk.Checkbutton(pretrade_frame, text="Confirm rebound", variable=self._s_confirm_rebound)
        confirm_check.pack(side="left", padx=(8, 0))
        self._tip(confirm_check, SETTINGS_HELP["Confirm rebound"])
        self._s_require_dip = tk.BooleanVar(value=config.FUTURES_REQUIRE_DIP)
        dip_check = ttk.Checkbutton(pretrade_frame, text="Require dip", variable=self._s_require_dip)
        dip_check.pack(side="left", padx=(8, 0))
        self._tip(dip_check, SETTINGS_HELP["Require dip"])
        self._tip(pretrade_label, SETTINGS_HELP["Pre-trade wave check"])
        self._tip(pretrade_check, SETTINGS_HELP["Pre-trade wave check"])

        self._s_pretrade_score = tk.StringVar(value=str(round(config.PRE_TRADE_MIN_SCORE, 0)))
        row("Min pre-trade score", lambda p: field(p, self._s_pretrade_score, 8), 10)

        self._s_account_exposure = tk.StringVar(value=str(config.FUTURES_MAX_ACCOUNT_LEVERAGE))
        row("Account exposure (x)", lambda p: field(p, self._s_account_exposure, 8), 11)
        self._s_cash_reserve = tk.StringVar(value=str(config.FUTURES_CASH_RESERVE_PCT * 100))
        row("Cash reserve (%)", lambda p: field(p, self._s_cash_reserve, 8), 12)
        self._s_exchange = tk.StringVar(value=config.FUTURES_EXCHANGE)
        row("Futures exchange", lambda p: ttk.Combobox(p, textvariable=self._s_exchange,
            values=("okx", "binance"), state="readonly", style="Settings.TCombobox", width=10), 15)

        self._s_auto_start = tk.BooleanVar(value=config.AUTO_START_FUTURES)
        auto_frame = tk.Frame(grid, bg="#111214")
        auto_frame.grid(row=13, column=1, sticky="w", padx=8, pady=4)
        auto_label = ttk.Label(grid, text="Auto-start futures", foreground="#a0aab2", background="#111214",
                               font=(FONT, 9), width=22)
        auto_label.grid(row=13, column=0, sticky="w", pady=4)
        auto_check = ttk.Checkbutton(auto_frame, text="Enable on launch", variable=self._s_auto_start)
        auto_check.pack(side="left")
        self._tip(auto_label, SETTINGS_HELP["Auto-start futures"])
        self._tip(auto_check, SETTINGS_HELP["Auto-start futures"])

        self._s_ohverlay_enabled = tk.BooleanVar(value=config.OHVERLAY_ENABLED)
        ohverlay_frame = tk.Frame(grid, bg="#111214")
        ohverlay_frame.grid(row=14, column=1, sticky="w", padx=8, pady=4)
        ohverlay_label = ttk.Label(grid, text="Ohverlay alerts", foreground="#a0aab2", background="#111214",
                                   font=(FONT, 9), width=22)
        ohverlay_label.grid(row=14, column=0, sticky="w", pady=4)
        ohverlay_check = ttk.Checkbutton(ohverlay_frame, text="Enable bubbles", variable=self._s_ohverlay_enabled)
        ohverlay_check.pack(side="left")
        ohverlay_test = ttk.Button(ohverlay_frame, text="Test", style="Btn.TButton",
                                   command=self._send_ohverlay_test)
        ohverlay_test.pack(side="left", padx=(8, 0))
        self._tip(ohverlay_label, SETTINGS_HELP["Ohverlay alerts"])
        self._tip(ohverlay_check, SETTINGS_HELP["Ohverlay alerts"])
        self._tip(ohverlay_test, "Send a test bubble to Ohverlay's local webhook using the current checkbox value.")

        # Apply button
        setup_msg = "" if self._settings_confirmed else "First run: review these values, then click Apply Settings."
        self._s_status = tk.StringVar(value=setup_msg)
        bf = tk.Frame(settings_panel, bg="#111214")
        bf.pack(fill="x", pady=12)
        apply_settings_btn = ttk.Button(bf, text="Apply Settings", style="Btn.TButton",
                                        command=self._apply_settings)
        apply_settings_btn.pack(side="left")
        self._tip(apply_settings_btn, "Save settings to .env and apply them to new futures trades. Open trades keep original leverage, margin, TP, and SL.")
        ttk.Label(bf, textvariable=self._s_status, foreground="#47c997",
                  background="#111214", font=(FONT, 9), wraplength=510).pack(side="left", padx=12)

        ttk.Label(settings_panel,
                  text="Changes apply to new trades only. Open positions keep their original settings.",
                  foreground="#a0aab2", background="#111214",
                  font=(FONT, 8)).pack(anchor="w")

        self._account_summary_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self._account_summary_var, wraplength=370,
                  foreground="#59dcb2", background="#111214", font=(FONT, 10),
                  justify="left").pack(side="left", anchor="n", padx=(20, 0))
        def attach_wheel(widget):
            widget.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units"), add="+")
            for child in widget.winfo_children():
                attach_wheel(child)
        attach_wheel(body)

    def _send_ohverlay_test(self):
        previous = config.OHVERLAY_ENABLED
        config.OHVERLAY_ENABLED = self._s_ohverlay_enabled.get()
        try:
            ov.send_event(
                "TradingBot23 Test",
                [
                    "Ohverlay bubble notifications are connected.",
                    "Enable Ohverlay's Webhook Server if no bubble appears.",
                ],
                source="tradingbot23-test",
            )
            self._s_status.set(
                "Ohverlay test sent." if config.OHVERLAY_ENABLED
                else "Ohverlay test skipped: checkbox is OFF."
            )
        finally:
            config.OHVERLAY_ENABLED = previous

    def _apply_settings(self):
        if not self._account_lock.acquire(blocking=False):
            self._s_status.set("Scan is busy. Apply again when the current scan finishes.")
            return
        try:
            self._apply_settings_locked()
        except (ValueError, OSError) as exc:
            self._s_status.set(f"Settings not applied: {exc}")
        finally:
            self._account_lock.release()

    def _apply_settings_locked(self):
        try:
            capital   = float(self._s_capital.get())
            leverage  = int(self._s_leverage.get())
            tp_pct    = float(self._s_tp.get()) / 100
            sl_on     = self._s_sl_enabled.get()
            sl_pct    = float(self._s_sl.get()) / 100
            crash_entry_guard = self._s_crash_entry_guard.get()
            crash_emergency_sl = self._s_crash_emergency_sl.get()
            btc_filter_raw = self._s_btc_regime_filter.get().strip()
            btc_regime_filter = (
                None
                if btc_filter_raw.lower() in {"", "none", "off"}
                else float(btc_filter_raw) / 100
            )
            hold_days = int(self._s_hold.get())
            per_trade = float(self._s_per_trade.get()) / 100
            max_open_trades = int(self._s_max_open_trades.get())
            pretrade_enabled = self._s_pretrade_enabled.get()
            pretrade_score = float(self._s_pretrade_score.get())
            confirm_rebound = self._s_confirm_rebound.get()
            require_dip = self._s_require_dip.get()
            exposure = float(self._s_account_exposure.get())
            reserve = float(self._s_cash_reserve.get()) / 100
            exchange = self._s_exchange.get()
            auto_start = self._s_auto_start.get()
            ohverlay_enabled = self._s_ohverlay_enabled.get()
        except ValueError as e:
            self._s_status.set(f"Error: {e}")
            return

        values = [capital, tp_pct, sl_pct, per_trade, exposure, reserve, pretrade_score]
        if btc_regime_filter is not None:
            values.append(btc_regime_filter)
        if not all(math.isfinite(value) for value in values):
            self._s_status.set("Error: settings must be finite numbers")
            return
        if capital <= 0 or tp_pct <= 0 or sl_pct <= 0 or hold_days < 1 or not 0 < per_trade <= 1:
            self._s_status.set("Error: capital/TP/SL/hold must be positive; per trade must be 0-100%")
            return
        leverage = max(1, min(leverage, config.MAX_LEVERAGE))
        self._s_leverage.set(leverage)
        if exposure < 0 or not 0 <= reserve < 1 or exchange not in {"okx", "binance"}:
            self._s_status.set("Error: invalid exposure cap, reserve or exchange")
            return
        if not 1 <= max_open_trades <= config.MAX_OPEN_TRADES_CAP:
            self._s_status.set(f"Error: max open trades must be 1-{config.MAX_OPEN_TRADES_CAP}")
            return
        if not 0 <= pretrade_score <= 100:
            self._s_status.set("Error: min pre-trade score must be 0-100")
            return
        if exchange != config.FUTURES_EXCHANGE and self.trader.get_open_positions():
            self._s_status.set("Close/reset existing paper trades before changing their price source.")
            return
        try:
            capital_cash_delta = self.trader.starting_capital_delta(capital)
            if self.trader.cash_balance + capital_cash_delta < -0.005:
                self._s_status.set(
                    f"Error: capital decrease needs ${abs(capital_cash_delta):,.2f} free cash; "
                    f"available cash is ${self.trader.cash_balance:,.2f}."
                )
                return
        except ValueError as e:
            self._s_status.set(f"Error: {e}")
            return

        # Save to .env
        self._write_env({
            "CAPITAL_USD":        capital,
            "LEVERAGE":           leverage,
            "FUTURES_NET_TP_PCT": tp_pct,
            "FUTURES_NET_SL_PCT": sl_pct,
            "FUTURES_USE_SL":     "true" if sl_on else "false",
            "CRASH_ENTRY_GUARD_ENABLED": "true" if crash_entry_guard else "false",
            "CRASH_EMERGENCY_SL_ENABLED": "true" if crash_emergency_sl else "false",
            "BTC_REGIME_FILTER_PCT": "none" if btc_regime_filter is None else btc_regime_filter,
            "MAX_HOLD_DAYS":      hold_days,
            "PER_TRADE_PCT":      per_trade,
            "MAX_OPEN_TRADES":    max_open_trades,
            "PRE_TRADE_ANALYSIS_ENABLED": "true" if pretrade_enabled else "false",
            "PRE_TRADE_MIN_SCORE": pretrade_score,
            "PRE_TRADE_CONFIRMATION_ENABLED": "true" if confirm_rebound else "false",
            "FUTURES_REQUIRE_DIP": "true" if require_dip else "false",
            "FUTURES_MAX_ACCOUNT_LEVERAGE": exposure,
            "FUTURES_CASH_RESERVE_PCT": reserve,
            "FUTURES_EXCHANGE": exchange,
            "AUTO_START_FUTURES": "true" if auto_start else "false",
            "OHVERLAY_ENABLED": "true" if ohverlay_enabled else "false",
            "SETTINGS_CONFIRMED": "true",
        })

        # Hot-apply to config (new trades pick these up immediately)
        config.CAPITAL_USD        = capital
        config.LEVERAGE           = leverage
        config.FUTURES_NET_TP_PCT = tp_pct
        config.FUTURES_NET_SL_PCT = sl_pct
        config.FUTURES_USE_SL     = sl_on
        config.CRASH_ENTRY_GUARD_ENABLED = crash_entry_guard
        config.CRASH_EMERGENCY_SL_ENABLED = crash_emergency_sl
        config.BTC_REGIME_FILTER_PCT = btc_regime_filter
        config.MAX_HOLD_DAYS      = hold_days
        config.PER_TRADE_PCT      = per_trade
        old_max_open_trades = config.MAX_OPEN_TRADES
        config.MAX_OPEN_TRADES    = max_open_trades
        config.TOP_N_LOSERS       = max(config.TOP_N_LOSERS, config.MAX_OPEN_TRADES)
        config.PRE_TRADE_ANALYSIS_ENABLED = pretrade_enabled
        config.PRE_TRADE_MIN_SCORE = pretrade_score
        config.PRE_TRADE_CONFIRMATION_ENABLED = confirm_rebound
        config.FUTURES_REQUIRE_DIP = require_dip
        config.FUTURES_MAX_ACCOUNT_LEVERAGE = exposure
        config.FUTURES_CASH_RESERVE_PCT = reserve
        if exchange != config.FUTURES_EXCHANGE:
            config.FUTURES_EXCHANGE = exchange
            self.trader._client = None
            self.strategy.basket = []
            self.strategy.basket_month = None
        config.AUTO_START_FUTURES = auto_start
        config.OHVERLAY_ENABLED = ohverlay_enabled
        config.SETTINGS_CONFIRMED = True
        self._settings_confirmed = True
        if max_open_trades != old_max_open_trades:
            self.strategy.basket = []
            self.strategy.basket_month = None
            self.strategy.basket_year = None
        applied_capital_delta = self.trader.sync_starting_capital(capital)
        self.trader.leverage      = leverage
        self.engine_var.set(self._new_trade_setting_text())

        capital_note = ""
        if abs(applied_capital_delta) >= 0.01:
            sign = "+" if applied_capital_delta > 0 else "-"
            capital_note = f"  |  Cash {sign}${abs(applied_capital_delta):,.2f}"
        self._s_status.set(
            f"Applied!  Leverage: {leverage}x  |  Max open: {max_open_trades}  |  "
            f"Pretrade: {'ON' if pretrade_enabled else 'OFF'} {pretrade_score:.0f}  |  "
            f"TP: {tp_pct*100:.2f}%  |  SL: {'ON' if sl_on else 'OFF'}  |  "
            f"Crash: {'GUARD' if crash_entry_guard else 'OFF'}/"
            f"{'SL' if crash_emergency_sl else 'NO-SL'}  |  "
            f"BTC: {'OFF' if btc_regime_filter is None else f'{btc_regime_filter*100:+.2f}%'}  |  "
            f"Deposits ${capital:,.2f} | {exchange.upper()} | Ohverlay: {'ON' if ohverlay_enabled else 'OFF'}"
            f"{capital_note}")
        self._refresh_summary()

    @staticmethod
    def _new_trade_setting_text() -> str:
        return f"{config.FUTURES_EXCHANGE.upper()} Futures  /  {config.LEVERAGE}x cross  /  Max {config.MAX_OPEN_TRADES}"

    @staticmethod
    def _num(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _write_env(updates: dict) -> None:
        env_path = config.PROJECT_ROOT / ".env"
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        written = set()
        new_lines = []
        for line in lines:
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=")[0].strip()
                if key in updates:
                    new_lines.append(f"{key}={updates[key]}")
                    written.add(key)
                    continue
            new_lines.append(line)
        for key, val in updates.items():
            if key not in written:
                new_lines.append(f"{key}={val}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def _risk_snapshot(self) -> dict:
        open_positions = list(self.trader.get_open_positions())
        closed = list(self.trader.get_trade_history())
        portfolio = self.trader.get_portfolio_value()
        cash = self.trader.cash_balance
        open_notional = sum(self._num(getattr(pos, "notional", 0.0)) for pos in open_positions)
        open_margin = sum(self._num(getattr(pos, "margin_used", 0.0)) for pos in open_positions)
        today_key = datetime.now(timezone.utc).date()
        daily_pnl = 0.0
        for pos in closed:
            exit_time = getattr(pos, "exit_time", None)
            if exit_time and exit_time.astimezone(timezone.utc).date() == today_key:
                daily_pnl += self._num(getattr(pos, "pnl_usd", 0.0))

        sorted_closed = sorted(
            [p for p in closed if getattr(p, "exit_time", None)],
            key=lambda p: p.exit_time,
            reverse=True,
        )
        loss_streak = 0
        for pos in sorted_closed:
            if self._num(getattr(pos, "pnl_usd", 0.0)) < 0:
                loss_streak += 1
            else:
                break

        backtests = sorted(config.DATA_DIR.glob("backtest*.txt")) if config.DATA_DIR.exists() else []
        try:
            rebound = rebound_analysis.latest_study_summary(config.DATA_DIR)
        except Exception:
            logger.debug("Could not load rebound study summary", exc_info=True)
            rebound = {}
        return {
            "portfolio": portfolio,
            "cash": cash,
            "open_count": len(open_positions),
            "open_notional": open_notional,
            "open_margin": open_margin,
            "daily_pnl": daily_pnl,
            "loss_streak": loss_streak,
            "total_trades": len(closed),
            "profile": config.BOT_PROFILE,
            "data_dir": str(config.DATA_DIR),
            "backtest_count": len(backtests),
            "latest_backtest": backtests[-1].name if backtests else "none",
            "rebound": rebound,
        }

    def _risk_allows_trading(self) -> tuple[bool, list[str]]:
        snap = self._risk_snapshot()
        reasons: list[str] = []
        if self._risk_kill_switch:
            reasons.append("kill switch active")
        if config.RISK_MAX_DAILY_LOSS_USD > 0 and snap["daily_pnl"] <= -config.RISK_MAX_DAILY_LOSS_USD:
            reasons.append(f"daily loss {snap['daily_pnl']:+.2f} <= -{config.RISK_MAX_DAILY_LOSS_USD:.2f}")
        if config.RISK_MAX_OPEN_EXPOSURE_USD > 0 and snap["open_notional"] >= config.RISK_MAX_OPEN_EXPOSURE_USD:
            reasons.append(
                f"open notional {snap['open_notional']:.2f} >= {config.RISK_MAX_OPEN_EXPOSURE_USD:.2f}"
            )
        if config.RISK_MAX_LOSS_STREAK > 0 and snap["loss_streak"] >= config.RISK_MAX_LOSS_STREAK:
            reasons.append(f"loss streak {snap['loss_streak']} >= {config.RISK_MAX_LOSS_STREAK}")
        return not reasons, reasons

    def _apply_risk_settings(self):
        try:
            profile = self._risk_profile.get().strip() or "default"
            daily_loss = max(0.0, float(self._risk_max_daily_loss.get()))
            exposure = max(0.0, float(self._risk_max_exposure.get()))
            loss_streak = max(0, int(self._risk_max_loss_streak.get()))
        except ValueError as exc:
            self._risk_action_var.set(f"Error: {exc}")
            return

        self._write_env({
            "BOT_PROFILE": profile,
            "RISK_MAX_DAILY_LOSS_USD": daily_loss,
            "RISK_MAX_OPEN_EXPOSURE_USD": exposure,
            "RISK_MAX_LOSS_STREAK": loss_streak,
        })
        old_profile = config.BOT_PROFILE
        config.BOT_PROFILE = profile
        config.RISK_MAX_DAILY_LOSS_USD = daily_loss
        config.RISK_MAX_OPEN_EXPOSURE_USD = exposure
        config.RISK_MAX_LOSS_STREAK = loss_streak
        note = " Applied."
        if profile != old_profile:
            note += " Restart to switch data folder."
        self._risk_action_var.set(note.strip())
        self._record_decision("system", "risk_settings", "UPDATED", 80, "risk limits saved")
        self._refresh_risk_tab()

    def _risk_kill(self):
        self._risk_kill_switch = True
        self._paused = False
        self.pause_btn.config(text="Pause")
        self._force_event.set()
        self.status_var.set("Risk kill switch active. New entries are blocked; exits are still monitored.")
        self._risk_action_var.set("Kill switch active. Monitoring exits only.")
        self._record_decision("risk", "kill_switch", "BLOCK", 0, "manual kill switch; exits still monitored")
        try:
            append_event(
                domain="system",
                event_type="KILL_SWITCH",
                status="ACTIVE",
                amount=0,
                currency="",
                pnl=0,
                balance=self.trader.get_portfolio_value(),
                symbol_or_route="risk",
                details="manual dashboard kill switch",
            )
        except Exception:
            pass
        self._refresh_risk_tab()

    def _risk_clear_kill(self):
        self._risk_kill_switch = False
        self._risk_action_var.set("Kill switch cleared. Press Resume If Allowed if futures are paused.")
        self._record_decision("risk", "kill_switch", "UPDATED", 80, "manual kill switch cleared")
        self._refresh_risk_tab()

    def _risk_resume(self):
        allowed, reasons = self._risk_allows_trading()
        if not allowed:
            self._paused = False
            self.pause_btn.config(text="Pause")
            self._force_event.set()
            self._risk_action_var.set("Blocked: " + "; ".join(reasons))
            self._record_decision("risk", "resume", "BLOCK", 0, "; ".join(reasons))
            self._refresh_risk_tab()
            return
        self._paused = False
        self.pause_btn.config(text="Pause")
        self._force_event.set()
        self._risk_action_var.set("Resumed.")
        self._record_decision("risk", "resume", "RUN", 100, "risk checks passed")
        self._refresh_risk_tab()

    def _refresh_risk_tab(self):
        if not hasattr(self, "risk_tree"):
            return
        snap = self._risk_snapshot()
        allowed, reasons = self._risk_allows_trading()
        state_text = "OK" if allowed else "BLOCKED: " + "; ".join(reasons)
        self._risk_summary_var.set(
            f"Profile {snap['profile']}  |  Data {snap['data_dir']}  |  "
            f"Futures {'paused' if self._paused else 'running'}  |  Risk {state_text}"
        )
        for item in self.risk_tree.get_children():
            self.risk_tree.delete(item)

        def row(metric, value, limit="", status="OK", tag="ok"):
            self.risk_tree.insert("", "end", values=(metric, value, limit, status), tags=(tag,))

        row("Bot profile", snap["profile"], "restart required after change", "ACTIVE", "ok")
        row("Data folder", self._clip_text(snap["data_dir"], 64), "", "LOCAL", "ok")
        entry_tag = "ok" if allowed and not self._paused else "block" if not allowed else "warn"
        entry_status = "READY" if allowed and not self._paused else "BLOCKED" if not allowed else "PAUSED"
        entry_value = "entries allowed" if allowed and not self._paused else "; ".join(reasons) if reasons else "press Resume or Run Now"
        entry_limit = "risk guard + pause state"
        row("New futures entries", entry_value, entry_limit, entry_status, entry_tag)
        row(
            "Daily futures P&L",
            f"${snap['daily_pnl']:+,.2f}",
            f"-${config.RISK_MAX_DAILY_LOSS_USD:,.2f}" if config.RISK_MAX_DAILY_LOSS_USD else "disabled",
            "BLOCK" if config.RISK_MAX_DAILY_LOSS_USD and snap["daily_pnl"] <= -config.RISK_MAX_DAILY_LOSS_USD else "OK",
            "block" if config.RISK_MAX_DAILY_LOSS_USD and snap["daily_pnl"] <= -config.RISK_MAX_DAILY_LOSS_USD else "ok",
        )
        row(
            "Open futures notional",
            f"${snap['open_notional']:,.2f} ({snap['open_count']} positions)",
            f"${config.RISK_MAX_OPEN_EXPOSURE_USD:,.2f}" if config.RISK_MAX_OPEN_EXPOSURE_USD else "disabled",
            "BLOCK" if config.RISK_MAX_OPEN_EXPOSURE_USD and snap["open_notional"] >= config.RISK_MAX_OPEN_EXPOSURE_USD else "OK",
            "block" if config.RISK_MAX_OPEN_EXPOSURE_USD and snap["open_notional"] >= config.RISK_MAX_OPEN_EXPOSURE_USD else "ok",
        )
        row(
            "Loss streak",
            str(snap["loss_streak"]),
            str(config.RISK_MAX_LOSS_STREAK) if config.RISK_MAX_LOSS_STREAK else "disabled",
            "BLOCK" if config.RISK_MAX_LOSS_STREAK and snap["loss_streak"] >= config.RISK_MAX_LOSS_STREAK else "OK",
            "block" if config.RISK_MAX_LOSS_STREAK and snap["loss_streak"] >= config.RISK_MAX_LOSS_STREAK else "ok",
        )
        row("Open margin", f"${snap['open_margin']:,.2f}", "", "TRACK", "ok")
        rebound = snap.get("rebound") or {}
        if rebound:
            row(
                "5Y rebound study",
                f"hit {rebound.get('hit_rate_pct')}% | med {rebound.get('median_days')}d | p90 {rebound.get('p90_days')}d",
                f"dip<=-2% -> TP {rebound.get('target_pct')}%",
                f"{rebound.get('events')} events",
                "ok",
            )
            coverage_total = int(self._num(rebound.get("coverage_total")))
            coverage_ok = int(self._num(rebound.get("coverage_ok")))
            row(
                "Rebound coverage",
                f"{coverage_ok}/{coverage_total} symbols",
                self._clip_text(rebound.get("generated_name", ""), 42),
                "CURRENT TOP-50 BIAS",
                "warn",
            )
        else:
            row("5Y rebound study", "not run yet", "Run 5Y Rebound", "MISSING", "warn")
        row("Backtest files", f"{snap['backtest_count']} | latest {snap['latest_backtest']}", "", "FORWARD TESTING", "ok")
        self._refresh_decision_tree()

    def _fit_risk_panes(self):
        panes = getattr(self, "_risk_panes", None)
        if panes is None:
            return
        try:
            height = panes.winfo_height()
            if height <= 1:
                self.root.after(150, self._fit_risk_panes)
                return
            first_pane_height = max(135, height - 175)
            panes.sash_place(0, 0, first_pane_height)
        except tk.TclError:
            return

    def _run_rebound_study(self):
        if self._rebound_study_running:
            self._risk_action_var.set("5Y rebound study already running...")
            return
        self._rebound_study_running = True
        self._risk_action_var.set("Running 5Y rebound study in background...")
        self._record_decision("research", "5y_rebound", "RUN", 80, "background study started")

        def worker():
            try:
                rebound_analysis.main()
                summary = rebound_analysis.latest_study_summary(config.DATA_DIR)
                if summary:
                    status = (
                        f"5Y rebound updated: hit {summary.get('hit_rate_pct')}%, "
                        f"p90 {summary.get('p90_days')}d"
                    )
                else:
                    status = "5Y rebound study finished; summary not found."
                self._record_decision("research", "5y_rebound", "UPDATED", 90, status)
            except Exception as exc:
                logger.exception("5Y rebound study failed")
                status = f"5Y rebound study failed: {exc}"
                self._record_decision("research", "5y_rebound", "BLOCK", 0, status)
            finally:
                self._rebound_study_running = False
                try:
                    self.root.after(0, lambda: self._risk_action_var.set(status))
                    self.root.after(0, self._refresh_risk_tab)
                except tk.TclError:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _record_decision(
        self,
        domain: str,
        action: str,
        decision: str,
        score: float,
        reason: str,
        details: str = "",
    ):
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "domain": domain,
            "action": action,
            "decision": decision,
            "score": f"{score:.0f}",
            "reason": reason,
            "details": details,
        }
        self._decision_log.append(row)
        self._decision_log = self._decision_log[-300:]
        if hasattr(self, "decision_tree"):
            try:
                self.root.after(0, self._refresh_decision_tree)
            except tk.TclError:
                pass

    def _refresh_decision_tree(self):
        if not hasattr(self, "decision_tree"):
            return
        for item in self.decision_tree.get_children():
            self.decision_tree.delete(item)
        for row in reversed(self._decision_log[-80:]):
            decision = row.get("decision", "")
            tag = "block" if decision in {"BLOCK", "SKIP"} else "go" if decision in {"RUN", "FILLED", "UPDATED"} else "wait"
            self.decision_tree.insert("", "end", tags=(tag,), values=(
                row.get("timestamp", "")[:16].replace("T", " "),
                row.get("domain", ""),
                row.get("action", ""),
                decision,
                row.get("score", ""),
                self._clip_text(row.get("reason", ""), 80),
            ))

    def _refresh_event_ledger(self):
        if not hasattr(self, "ledger_tree"):
            return
        rows = self.event_ledger.recent(limit=300)
        for item in self.ledger_tree.get_children():
            self.ledger_tree.delete(item)
        for row in reversed(rows):
            pnl = self._num(row.get("pnl"))
            domain = row.get("domain", "")
            tag = "system" if domain == "system" else "profit" if pnl > 0 else "loss" if pnl < 0 else ""
            currency = row.get("currency", "")
            self.ledger_tree.insert("", "end", tags=(tag,), values=(
                row.get("timestamp", "")[:16].replace("T", " "),
                domain,
                row.get("event_type", ""),
                row.get("status", ""),
                f"{self._num(row.get('amount')):,.2f} {currency}".strip(),
                f"{pnl:+,.2f}" if pnl else "--",
                f"{self._num(row.get('balance')):,.2f}" if self._num(row.get("balance")) else "--",
                row.get("symbol_or_route", ""),
                self._clip_text(row.get("details", ""), 72),
            ))
        self._ledger_summary_var.set(f"{len(rows)} recent event(s)  |  CSV: {self.event_ledger.path}")

    def _export_ops_report(self):
        out = self._write_ops_report()
        if hasattr(self, "_risk_action_var"):
            self._risk_action_var.set(f"Report exported: {out.name}")
        return out

    def _write_ops_report(self):
        snap = self._risk_snapshot()
        stats = self.trader.get_stats()
        allowed, reasons = self._risk_allows_trading()
        ledger_rows = self.event_ledger.recent(limit=25)
        decisions = self._decision_log[-25:]
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "TradingBot23 Operations Report",
            f"Generated: {generated}",
            "",
            f"Profile: {snap['profile']}",
            f"Data folder: {snap['data_dir']}",
            f"Risk state: {'OK' if allowed else 'BLOCKED - ' + '; '.join(reasons)}",
            "",
            "Futures",
            f"  Portfolio: ${snap['portfolio']:,.2f}",
            f"  Cash: ${snap['cash']:,.2f}",
            f"  Daily closed P&L: ${snap['daily_pnl']:+,.2f}",
            f"  Open positions: {snap['open_count']}",
            f"  Open notional: ${snap['open_notional']:,.2f}",
            f"  Trades: {stats.get('total_trades', 0)} | Win rate: {stats.get('win_rate', 0):.1f}%",
        ]
        rebound = snap.get("rebound") or {}
        if rebound:
            lines.extend([
                f"  5Y rebound: hit {rebound.get('hit_rate_pct')}% | "
                f"median {rebound.get('median_days')}d | p90 {rebound.get('p90_days')}d",
                f"  Rebound report: {rebound.get('report_path')}",
            ])
        lines.extend([
            "",
            "Recent Decisions",
        ])
        for row in decisions:
            lines.append(
                f"  {row['timestamp'][:16]} {row['domain']} {row['action']} "
                f"{row['decision']} score={row['score']} {row['reason']}"
            )
        lines.append("")
        lines.append("Recent Ledger Events")
        for row in ledger_rows:
            lines.append(
                f"  {row.get('timestamp','')[:16]} {row.get('domain','')} "
                f"{row.get('event_type','')} {row.get('status','')} "
                f"pnl={row.get('pnl','')} {row.get('details','')}"
            )
        out = config.DATA_DIR / f"ops_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return out

    def _on_tab_changed(self, event):
        nb  = event.widget
        tab = nb.tab(nb.select(), "text").strip()
        if tab == "Risk":
            self._refresh_risk_tab()
            self.root.after(50, self._fit_risk_panes)
        elif tab == "Charts":
            self._draw_charts()
        elif tab == "History":
            self._refresh_history()
        elif tab == "Ledger":
            self._refresh_event_ledger()

    # ── Button handlers ────────────────────────────────────────────────────────

    def _require_settings_confirmation(self, message):
        self.notebook.select(self.settings_tab)
        self.status_var.set(message)

    def _on_run_now(self):
        if not self._settings_confirmed:
            self._require_settings_confirmation("Review Settings and click Apply Settings before running futures.")
            return
        allowed, reasons = self._risk_allows_trading()
        if not allowed:
            self.status_var.set("Run blocked by risk guard: " + "; ".join(reasons))
            self._record_decision("risk", "run_now", "BLOCK", 0, "; ".join(reasons))
            return
        if self._paused:
            self._paused = False
            self.pause_btn.config(text="Pause")
        self._force_event.set()
        self._record_decision("futures", "run_now", "RUN", 100, "manual run requested")
        self.status_var.set("Running cycle now...")

    def _on_pause_resume(self):
        if not self._settings_confirmed:
            self._require_settings_confirmation("Review Settings and click Apply Settings before starting futures.")
            return
        if self._paused:
            allowed, reasons = self._risk_allows_trading()
            if not allowed:
                self._paused = False
                self.pause_btn.config(text="Pause")
                self._force_event.set()
                self.status_var.set("Resume blocked by risk guard: " + "; ".join(reasons))
                self._record_decision("risk", "resume", "BLOCK", 0, "; ".join(reasons))
                return
        self._paused = not self._paused
        if self._paused:
            self.pause_btn.config(text="Resume")
            self._force_event.set()
            self.status_var.set("Entries paused; existing positions are still monitored.")
            self._record_decision("futures", "pause", "BLOCK", 0, "manual pause")
        else:
            self.pause_btn.config(text="Pause")
            self._force_event.set()
            self._record_decision("futures", "resume", "RUN", 100, "manual resume")
            self.status_var.set("Resumed")

    # ── Trading loop ───────────────────────────────────────────────────────────

    def _start_trading_loop(self):
        self._cycle_thread = threading.Thread(target=self._trading_loop, daemon=True)
        self._cycle_thread.start()

    def _run_guarded_cycle(self):
        with self._account_lock:
            allowed, reasons = self._risk_allows_trading()
            one_shot = self._one_shot_requested
            self._one_shot_requested = False
            if self._paused and not one_shot:
                allowed, reasons = False, ["entries paused"]
            if not self._settings_confirmed:
                allowed, reasons = False, ["settings not confirmed"]
            if not allowed:
                closed = self.trader.check_positions()
                return {"timestamp": datetime.now(timezone.utc).isoformat(),
                        "positions_opened": 0, "positions_closed": len(closed),
                        "risk_blocked": True, "risk_reasons": reasons}
            summary = self.strategy.run_cycle()
            self._record_decision("futures", "cycle", "RUN", 80,
                f"opened {summary.get('positions_opened', 0)} closed {summary.get('positions_closed', 0)} "
                f"prewait {summary.get('pre_trade_wait', 0)}")
            for row in summary.get("pre_trade_decisions", [])[-12:]:
                self._record_decision("futures", f"pretrade {row.get('symbol', '')}",
                    row.get("decision", "WAIT"), self._num(row.get("score")), row.get("reason", ""))
            return summary

    def _trading_loop(self):
        from bot.modules import telegram_notifier as tg
        now = datetime.now(timezone.utc)
        if self._settings_confirmed and self.strategy.should_refresh_basket(now):
            try:
                self.strategy.refresh_basket(now)
            except Exception:
                logger.exception("Failed to refresh basket")

        scan_interval    = config.POSITION_CHECK_MINS * 60
        last_summary_day = now.day  # send daily summary once per day

        while self._running:
            if self._paused and not self._one_shot_requested and not self.trader.get_open_positions():
                self._force_event.wait(timeout=1)
                self._force_event.clear()
                continue

            now_ts = time.time()
            force  = self._force_event.is_set()
            if force:
                self._force_event.clear()

            # Full cycle every 5 min: check positions + scan dips + fill empty slots
            try:
                summary = self._run_guarded_cycle()
                self._last_cycle_time    = datetime.now(timezone.utc)
                self._last_cycle_summary = summary
                self._next_cycle_ts      = now_ts + scan_interval
                if self._bridge_scan_id and self._bridge:
                    self._bridge.complete(self._bridge_scan_id, summary=summary)
                    self._bridge_scan_id = None
            except Exception:
                logger.exception("Error in trading cycle")
                if self._bridge_scan_id and self._bridge:
                    self._bridge.complete(self._bridge_scan_id, "failed", error="Scan failed; consult private logs")
                    self._bridge_scan_id = None

            # Record equity snapshot
            try:
                pv = self.trader.get_portfolio_value()
                with self._equity_lock:
                    self._equity_history.append((datetime.now(timezone.utc), pv))
                    if len(self._equity_history) > 5000:
                        self._equity_history = self._equity_history[-5000:]
            except Exception:
                pass

            # Daily summary alert at midnight UTC
            try:
                today = datetime.now(timezone.utc).day
                if today != last_summary_day:
                    last_summary_day = today
                    stats = self.trader.get_stats()
                    tg.alert_summary(
                        portfolio=self.trader.get_portfolio_value(),
                        cash=self.trader.cash_balance,
                        open_pos=len(list(self.trader.get_open_positions())),
                        total_trades=stats.get("total_trades", 0),
                        win_rate=stats.get("win_rate", 0),
                        total_pnl_usd=sum(
                            p.pnl_usd for p in self.trader.get_trade_history()
                        ),
                    )
            except Exception:
                pass

            self._force_event.wait(timeout=scan_interval)

    # ── UI refresh ─────────────────────────────────────────────────────────────

    def _schedule_refresh(self):
        if not self._running:
            return
        self._refresh_ui()
        self.root.after(self.REFRESH_MS, self._schedule_refresh)

    def _refresh_ui(self):
        try:
            self._update_clock()
            self._update_status()
            self._update_stats()
            self._update_positions()
            self._update_closed()
            self._update_basket()
            if hasattr(self, "_account_summary_var"):
                self._account_summary_var.set(
                    f"PAPER ACCOUNT\n\nDeposits: ${self.trader.get_contributed_capital():,.2f}\n"
                    f"Free cash: ${self.trader.cash_balance:,.2f}\n"
                    f"Net equity: ${self.trader.get_equity_breakdown()['estimated_net_equity_usd']:,.2f}\n\n"
                    f"{config.FUTURES_EXCHANGE.upper()} / CROSS\n"
                    f"Exposure cap: {config.FUTURES_MAX_ACCOUNT_LEVERAGE:g}x account\n"
                    f"Cash reserve: {config.FUTURES_CASH_RESERVE_PCT:.0%}\n\n"
                    f"LUM bridge: {'READY' if self._bridge else 'OFF'}")
            if hasattr(self, "notebook"):
                tab = self.notebook.tab(self.notebook.select(), "text").strip()
                if tab == "Risk":
                    self._refresh_risk_tab()
        except Exception:
            logger.debug("Dashboard refresh error", exc_info=True)


    def _update_clock(self):
        self.clock_label.config(
            text=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

    def _update_status(self):
        self.pause_btn.configure(image=self._icons["play" if self._paused else "pause"])
        self._run_state_var.set("Paused" if self._paused else "Running")
        if not self._settings_confirmed:
            self.status_var.set("First run: review Settings and click Apply Settings before trading.")
            return
        if self._paused:
            self.status_var.set("Entries paused. Existing exposure is monitored; Resume enables new entries.")
            return
        allowed, reasons = self._risk_allows_trading()
        if not allowed:
            self.status_var.set("Risk guard active; monitoring exits only: " + "; ".join(reasons))
            return
        if self._last_cycle_time is None:
            self.status_var.set("Waiting for first cycle...")
            return
        s         = self._last_cycle_summary
        last      = self._last_cycle_time.strftime("%H:%M:%S")
        secs_left = max(0, int(self._next_cycle_ts - time.time()))
        m, sec    = divmod(secs_left, 60)
        countdown = f"{m:02d}:{sec:02d}"
        if s.get("market_regime_blocked"):
            self.status_var.set(
                f"Market regime guard active; monitoring exits only: "
                f"{s.get('market_regime_reason', '')}  |  Next scan: {countdown}"
            )
            return
        self.status_var.set(
            f"Last: {last} UTC  |  Next scan: {countdown}  |  "
            f"Dips: {s.get('dips_found',0)}  "
            f"Opened: {s.get('positions_opened',0)}  "
            f"Filled: {s.get('slots_filled',0)}  "
            f"Closed: {s.get('positions_closed',0)}"
        )

    def _update_stats(self):
        breakdown      = self.trader.get_equity_breakdown()
        portfolio      = breakdown["estimated_net_equity_usd"]
        cash           = self.trader.cash_balance
        stats          = self.trader.get_stats()
        initial        = (
            self.trader.get_contributed_capital()
            if hasattr(self.trader, "get_contributed_capital")
            else config.CAPITAL_USD
        )
        pnl_pct        = ((portfolio - initial) / initial) * 100 if initial > 0 else 0
        open_positions = list(self.trader.get_open_positions())  # snapshot

        self.portfolio_var.set(f"${portfolio:,.2f}")
        self.cash_var.set(f"${cash:,.2f}")
        self.pnl_var.set(f"{pnl_pct:+.2f}%")
        self._metric_values["Total return"].configure(foreground=SUCCESS if pnl_pct >= 0 else DANGER)
        self.open_var.set(str(len(open_positions)))
        self.trades_var.set(str(stats.get("total_trades", 0)))
        self.winrate_var.set(f"{stats.get('win_rate', 0):.1f}%")
        self.profit_breakdown_var.set(
            f"Realized ${breakdown['realized_net_pnl_usd']:+,.2f}  |  "
            f"Open net est. ${breakdown['unrealized_net_pnl_usd']:+,.2f}  |  "
            f"Exit fee est. ${breakdown['estimated_exit_fees_usd']:,.2f}  |  "
            f"Funding est. ${breakdown['estimated_funding_usd']:,.2f}"
        )

    def _update_positions(self):
        for item in self.pos_tree.get_children():
            self.pos_tree.delete(item)
        now            = datetime.now(timezone.utc)
        self.trader.refresh_cross_liquidation_prices()
        open_positions = list(self.trader.get_open_positions())  # snapshot — no race condition
        self._positions_count.set(f"{len(open_positions)} / {config.MAX_OPEN_TRADES}")
        if open_positions:
            self._open_empty.place_forget()
        else:
            self._open_empty.place(relx=0.5, rely=0.5, anchor="center")
        for index, pos in enumerate(open_positions):
            age_h   = (now - pos.entry_time).total_seconds() / 3600
            current = pos.last_known_price or pos.entry_price
            pos.tp_price = self.trader._net_tp_price(pos, now)
            leverage = getattr(pos, "leverage", 1)
            if current and pos.entry_price > 0:
                price_chg = (current - pos.entry_price) / pos.entry_price
                estimate = self.trader.estimate_position_pnl(pos, now)
                pnl_str = f"{estimate['pnl_pct']:+.2f}% ({price_chg*100:+.2f}% price)"
            else:
                pnl_str = "--"
            risk_price = self._num(getattr(pos, "liquidation_price", 0.0), 0.0)
            risk_str = self._price_text(risk_price) if 0 < risk_price < pos.entry_price else "No near liq"
            self.pos_tree.insert("", "end", tags=("odd" if index % 2 else "even",), values=(
                pos.symbol,
                f"${pos.amount_usd:.2f}",
                f"{leverage}x",
                self._price_text(pos.entry_price),
                self._price_text(current) if current else "--",
                pnl_str,
                f"{pos.entry_change_24h:+.2f}%",
                self._price_text(pos.tp_price),
                risk_str,
                f"{age_h:.1f}h",
            ))

    def _update_closed(self):
        for item in self.closed_tree.get_children():
            self.closed_tree.delete(item)
        closed = list(self.trader.get_trade_history())  # snapshot
        for index, pos in enumerate(reversed(closed[-10:])):
            exit_t  = getattr(pos, "exit_time", None)
            t_str   = exit_t.strftime("%m/%d %H:%M") if exit_t else "--"
            reason  = getattr(pos, "status", "--")
            if hasattr(reason, "value"):
                reason = reason.value
            leverage = getattr(pos, "leverage", 1)
            self.closed_tree.insert("", "end", tags=("odd" if index % 2 else "even",), values=(
                pos.symbol,
                f"${pos.amount_usd:.2f}",
                f"{leverage}x",
                self._price_text(pos.entry_price),
                self._price_text(pos.exit_price) if pos.exit_price else "--",
                f"{pos.pnl_pct:+.2f}%",
                f"${pos.pnl_usd:+.2f}",
                f"{pos.entry_change_24h:+.2f}%",
                reason,
                t_str,
            ))

    def _update_basket(self):
        if self.strategy.basket:
            syms = [c["symbol"] for c in self.strategy.basket]
            ms   = (f" ({self.strategy.basket_year}-{self.strategy.basket_month:02d})"
                    if self.strategy.basket_month else "")
            self.basket_var.set(f"Basket{ms}: {', '.join(syms)}")
        else:
            self.basket_var.set("Basket: waiting for first cycle...")

    def _start_local_bridge(self):
        if not config.LOCAL_BRIDGE_ENABLED:
            return
        try:
            self._bridge = LocalBridge(config.DATA_DIR, config.LOCAL_BRIDGE_PORT)
            logger.info("LUM paper control bridge listening on %s", self._bridge.url)
            self.root.after(300, self._pump_local_bridge)
        except OSError:
            logger.exception("Local bridge unavailable; no remote controls enabled")

    def _pump_local_bridge(self):
        if not self._running or not self._bridge:
            return
        try:
            operation = self._bridge.commands.get_nowait()
        except queue.Empty:
            operation = None
        if operation:
            action, operation_id = operation["action"], operation["id"]
            allowed, reasons = self._risk_allows_trading()
            if action != "pause" and (not self._settings_confirmed or not allowed):
                self._bridge.complete(operation_id, "rejected", error="Settings/risk guard blocks entries", reasons=reasons)
            elif action == "pause":
                self._paused = True
                self.pause_btn.config(text="Resume")
                self._force_event.set()
                self._bridge.complete(operation_id, entries_paused=True)
            elif action == "resume":
                self._paused = False
                self.pause_btn.config(text="Pause")
                self._force_event.set()
                self._bridge.complete(operation_id, entries_paused=False)
            elif self._bridge_scan_id or not self._account_lock.acquire(blocking=False):
                self._bridge.complete(operation_id, "rejected", error="A scan or account operation is busy")
            else:
                try:
                    self._bridge_scan_id = operation_id
                    self._one_shot_requested = True
                    self._bridge.complete(operation_id, "running")
                    self._force_event.set()
                finally:
                    self._account_lock.release()
            self._record_decision("bridge", action, "REQUEST", 0, f"LUM local operation {operation_id}")
        if self._account_lock.acquire(blocking=False):
            try:
                self._bridge.publish(self._bridge_snapshot())
            finally:
                self._account_lock.release()
        self.root.after(300, self._pump_local_bridge)

    def _bridge_snapshot(self):
        trader = self.trader
        return {"ready": True, "mode": "paper", "live_orders_enabled": False,
                "exchange": config.FUTURES_EXCHANGE, "entries_paused": self._paused,
                "deposits_usd": trader.get_contributed_capital(), "cash_usd": trader.cash_balance,
                "equity": trader.get_equity_breakdown(), "stats": trader.get_stats(),
                "last_cycle": self._last_cycle_summary, "max_open_trades": config.MAX_OPEN_TRADES,
                "exposure_cap_x": config.FUTURES_MAX_ACCOUNT_LEVERAGE,
                "open_positions": [{"symbol": p.symbol, "leverage": p.leverage,
                    "mark_updated_at": p.mark_updated_at,
                    "margin_usd": p.margin_used, **trader.estimate_position_pnl(p)}
                    for p in trader.get_open_positions()],
                "history": [{"symbol": p.symbol, "pnl_usd": p.pnl_usd, "reason": p.status.value,
                    "closed_at": p.exit_time.isoformat() if p.exit_time else None}
                    for p in trader.get_trade_history()[-50:]],
                "p2p": {"enabled": False, "reason": "Retired; preserved local audit only"}}

    def _on_close(self):
        self._running = False
        self._force_event.set()
        if self._telegram_commands:
            self._telegram_commands.stop()
        if self._bridge:
            self._bridge.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
        self._running = False
        if self._telegram_commands:
            self._telegram_commands.stop()
