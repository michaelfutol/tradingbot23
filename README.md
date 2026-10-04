# TradingBot23

Private-use, futures-only paper trading with OKX public USDT perpetual data,
net performance reporting and a local control bridge for LUM/Desktop Commander.
No live orders, fiat payments, withdrawals or transfers are implemented.

## Windows Build

The newest successful build is in GitHub **Actions > Build TradingBot23.exe >
Artifacts > TradingBot23-Windows**. Extract the ZIP and run `TradingBot23.exe`.
Release downloads change only when a release is published, not on every push.
First launch starts paused until Settings are confirmed. Keep your private
`.env` and `data` folder outside GitHub; beta testers must start with their own.

## Current Workflow

| View | Purpose |
| --- | --- |
| Open | Entry leverage, margin, cached marks, estimated net P&L and cross liquidation |
| Risk | Entry guards, notional limits, optional daily-loss/streak limits and decisions |
| Charts | Session equity and closed-trade performance |
| History | Net fills, expectancy, profit factor, exports and archived paper resets |
| Ledger | Local audit of account operations, including preserved legacy events |
| Settings | Total deposited capital, exchange, leverage, targets, sizing and launch controls |

Binance P2P is retired from the active app, Telegram menu and automation.
Existing P2P data is left unchanged. Legacy P2P calculation modules/tests remain
offline for audit compatibility; a future P2P product will be separate.

### Capital

**Capital (USD)** is total deposited paper capital. It is not a new equity
balance and no monthly contribution is added on top. Apply increases/decreases
free cash by the deposit difference, preserving realized profit/loss and open
positions. A withdrawal requiring more than free cash is rejected.

Old monthly records are preserved in `account_state.json` as read-only evidence.
On upgrade the old baseline is reconciled once against the configured total
capital, with a capital-adjustment event, not rewritten as trading profit.
**Reset Futures Paper** archives the old session and starts a clean one at the
configured total capital. It requires confirmation and leaves scanning paused.

### Strategy And Exposure

The monthly candidate basket comes from the configured **top 50 market-cap**
universe, excluding stablecoins and coins outside the fresh rank/volume guard.
The selected exchange must have a usable derivatives instrument. Entries wait
for a dip, validated completed 15m candles, rebound confirmation and BTC regime
checks. No-data/stale-data candidates are rejected, not treated as an entry.
The wave score is deterministic analysis, not a trained AI or win probability.

The default total-notional cap is **3x estimated net account equity**, across
all trades, and the default free-cash reserve is **20%**. These size/block new
entries; they do not force-close positions. A 20x entry setting does not mean
the whole account must carry 20x exposure. Set the cap to zero only deliberately
for paper stress testing. Stop-loss and emergency crash stop remain opt-in.
Cross liquidation is an approximate paper model, not OKX's tiered liquidation
engine, and cash reserves do not guarantee safety during a crash.

**Pause** stops new entries while continuing to check existing positions for
exits. Exchange switching is blocked while positions are open. Saved marks are
timestamped; failed refreshes cannot execute TP, SL or expiry at a stale mark.

Net equity and trade P&L include modeled fees and funding. Their rates are
configurable estimates, not your actual OKX fee tier or live funding accrual.
Paper fills do not prove real execution, liquidity, slippage or profitability.
Judge results using net expectancy, average win/loss, profit factor and open
drawdown, not win rate alone. Validate changes out of sample and forward-test
before considering a separate live-order integration.

## OKX Connection

Set `FUTURES_EXCHANGE=okx` in Settings or the private `.env`. Public market data
requires **no API key**. The connector validates active linear USDT swaps,
fresh marks and completed candles. Binance public futures compatibility remains
available for existing accounts, but there is no spot fallback.

```powershell
.\venv\Scripts\python.exe -m bot.okx_check
```

Optional read-only **demo** credential verification:

```ini
OKX_API_KEY=
OKX_API_SECRET=
OKX_API_PASSPHRASE=
```

```powershell
.\venv\Scripts\python.exe -m bot.okx_check --demo
```

Use demo keys with read permission, never withdrawal permission. The private
verification request is always marked `x-simulated-trading: 1`. This is not
demo order execution and does not enable live trading. See the
[official OKX API guide](https://www.okx.com/docs-v5/en/).

## LUM Control Bridge

See [LUM_BRIDGE.md](docs/LUM_BRIDGE.md) for Desktop Commander commands and limits.
The bridge belongs to the running desktop bot, binds only to `127.0.0.1`,
requires a rotating private token and publishes cached account snapshots.
One data directory can have only one GUI/CLI/API writer. Do not start another
bot to control the same account.

## Development

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m bot.main --dashboard
.\venv\Scripts\python.exe -m PyInstaller tradingbot23.spec --clean
```

Use `.env.example` as the configuration reference. The web draft uses a separate
private account directory with authenticated access, not the desktop bridge.
Public hosting is not configured. Historical backtests do not validate the new
OKX paper workflow; do not interpret them as a promise of future returns.

## UI Foundation

Desktop and web share the Trade23 mark, neutral surfaces and restrained mint
accent. The native window, taskbar and EXE use the custom icon, not Tk's feather.
The web dashboard switches from desktop tables to readable trade rows on phones
and has touch-sized navigation. `/about` is a local product-page foundation,
not a published website. Its clearly marked preview images use disposable test
data, never the personal account. See [UI_DESIGN.md](docs/UI_DESIGN.md).
