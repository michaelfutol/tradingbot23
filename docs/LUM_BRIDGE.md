# LUM / Desktop Commander Bridge

Purpose: control the already-running TradingBot23 paper account on this Windows
PC. Do not launch a second strategy, console loop, web API or exchange bot.

## This PC

Open `D:\projects\tradingbot23\dist\TradingBot23.exe` once. Its private access
file is `D:\projects\tradingbot23\dist\data\bridge_access.json` for the default
profile. The token rotates at startup and the file is removed on clean shutdown.
The Windows user running Desktop Commander must be trusted: same-user local
processes can read this file. Do not share it, print its token, upload it, forward
its port, tunnel it or expose it to a browser/web service.

```powershell
& 'D:\projects\tradingbot23\dist\TradingBot23.exe' --bridge status --access-file 'D:\projects\tradingbot23\dist\data\bridge_access.json'
& 'D:\projects\tradingbot23\dist\TradingBot23.exe' --bridge history --access-file 'D:\projects\tradingbot23\dist\data\bridge_access.json'
& 'D:\projects\tradingbot23\dist\TradingBot23.exe' --bridge pause --access-file 'D:\projects\tradingbot23\dist\data\bridge_access.json'
& 'D:\projects\tradingbot23\dist\TradingBot23.exe' --bridge run-once --access-file 'D:\projects\tradingbot23\dist\data\bridge_access.json'
& 'D:\projects\tradingbot23\dist\TradingBot23.exe' --bridge resume --access-file 'D:\projects\tradingbot23\dist\data\bridge_access.json'
```

`run-once` requests one guarded paper scan and retains the pause state. It may
open **zero** positions. A reply with `queued` or `running` is not completion.
Read the returned operation ID:

```powershell
& 'D:\projects\tradingbot23\dist\TradingBot23.exe' --bridge operation --id '<returned 24-character ID>' --access-file 'D:\projects\tradingbot23\dist\data\bridge_access.json'
```

`resume` enables scheduled scans; `pause` stops entries but monitors exits. A
scan already in progress can finish. Settings confirmation and risk/kill guards
cannot be bypassed through the bridge. If busy, wait for the current scan and
retry once; do not flood the command queue. Inspect `snapshot_at_unix`, mark
timestamps and `last_cycle` before calling a snapshot current.

Source users can substitute `.\venv\Scripts\python.exe -m bot.bridge_cli` for
the EXE prefix. Set `LOCAL_BRIDGE_ENABLED=false` to disable the bridge or change
`LOCAL_BRIDGE_PORT` before restarting. Other profiles use their own data paths.

## Authority Limits

Only status/history and pause/resume/run-once are supported. No arbitrary code,
shell commands, settings changes, capital withdrawals, resets, position closure,
credential retrieval, fiat payments or real exchange orders are exposed.
Capital and risk changes remain deliberate local UI actions by the human user.
P2P is retired; its legacy bridge endpoint only returns a disabled marker.

LUM should report realized net P&L, open net estimates, exposure and data age
separately. Do not report profitable opportunities as executed trades or promise
returns. This bridge permits control; it does not automatically schedule or
grant LUM persistent monitoring. A real OKX trading adapter needs a separate
review of instrument contract sizing, order reconciliation, exchange-native
stops, account permissions, fees, funding, network failures and audit trails.
