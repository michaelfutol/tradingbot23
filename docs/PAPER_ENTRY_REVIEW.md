# Paper entry review (2026-10-02)

A review of the local paper history found that a very high closed-trade win
rate could coexist with negative net expectancy: a single large leveraged
loss outweighed many small winners. Funding also reduced the net result.
Personal balances and transaction records stay in the local data directory,
not this public repository. Cross margin allows a position to consume shared
collateral beyond its own margin; a distant single-position liquidation
estimate does not prevent that.

These are descriptive figures from the saved CSV, not proof of a tradable edge.
Old builds could automatically rewrite TP/positive-liquidation history on
startup. Existing records are preserved as found, not "corrected" or treated
as independent validation of the new filters.

## Implemented

- Require the configured 24h dip by default; no automatic non-dip slot filling.
- Rank eligible candidates by wave score, not simply by the largest drop.
- Optional stricter confirmation: two rising completed 15m closes, positive
  1h momentum and a close above SMA20. Enabled by default for paper testing.
- Validate futures OHLC, timestamp ordering, continuity and freshness; exclude
  the forming candle. Missing BTC/coin analysis means WAIT, never permission
  to buy. Entry candle analysis does not silently substitute spot candles.
- Cache candidate decisions once per cycle to avoid repeat API calls and a
  rejected setup being rechecked during the same slot-fill pass.
- Record successful entries as ENTRY_QUALITY events in Ledger, tagged
  entry-quality-v1 with the score, filter switches and reason, so subsequent
  paper results can be matched to the new policy rather than mixed with old ones.
- Preserve historical fills/reasons/P&L rather than applying today's TP to old
  trades. New positions persist their net TP, fee and funding assumptions.
- Solve TP including exact modeled entry/exit fees and elapsed funding.
- Show net dollar expectancy, average wins/losses and profit factor in History.
- Keep normal/emergency stop-loss opt-in. Capital, leverage, max hold, account
  history and P2P settings are not reset by this update.

## Private-use follow-up

At the user's request, the packaged futures account was reset into a separate
session, archiving its prior records locally under `data/futures_sessions/`.
The monthly contribution ledger and P2P history were retained. Subsequent
eligible paper entries belong to the new session and are not reset again.

The personal desktop now shows estimated net equity, realized net P&L, open
net P&L, modeled exit fees and accrued funding. Open-table and Telegram P&L use
the same original-fee/funding calculation as the web API, rather than gross
leveraged returns or the unchanged closed-trade P&L field. Estimates use cached
marks and are not exchange-exact live balances. Existing entry, SL and
liquidation policies were not changed by this reporting update.

The web draft is authenticated, paper-only, and has remote cycles disabled by
default. Its CLI launch binds to localhost. Public hosting was put on hold at
the user's request; nothing was deployed to `trade23.futoltech.com`.

## Evidence Limits

Automated regression tests establish the entry/accounting behavior, not a
higher future win rate. These rules are deterministic, not trained AI or a
calibrated probability. Stricter confirmation can reduce trades, miss profitable
bounces and still admit losing setups. No parameter sweep on this short ledger
is presented as out-of-sample validation.

Forward-test the new entries separately, with unchanged settings. Compare net
expectancy, profit factor, drawdowns, unrealized losses, costs and trade counts,
not only closed-trade win rate. Do not go live on the strength of these tests:
real futures execution is still not implemented. Holding leveraged losers
without an SL still exposes the shared account to large losses and funding.

References:
- [CME: The Mathematics of Trading Success](https://www.cmegroup.com/education/courses/trading-psychology/the-mathematics-of-trading-success)
- [Binance USD-M futures documentation](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data)
