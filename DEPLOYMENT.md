# Trade23 Web Deployment

Target: `https://trade23.futoltech.com`. Local reset/reopen does not deploy the web
app, and a web account does not automatically mirror the desktop account.

## Hosting Gate

Before changing Namecheap/cPanel, confirm the authenticated account, hosting
server, subdomain document root, existing files, SSL, and available app runtime.
Back up existing content before replacing it. Do not change the main
`futoltech.com` document root.

The React frontend is static and can run on cPanel. The Python backend is
**FastAPI/ASGI**, which requires an ASGI server such as Uvicorn. cPanel's Python
Selector normally expects a **WSGI** callable: assigning `bot.api.app` directly
to `passenger_wsgi.application` is not a valid deployment. Confirm that the
hosting plan supports an always-on ASGI process and proxy before hosting the
engine there. Otherwise use cPanel for static files and an explicitly selected
ASGI backend host. Do not assume shared hosting supports a persistent bot.

References: [FastAPI server deployment](https://fastapi.tiangolo.com/deployment/manually/),
[cPanel Application Manager](https://docs.cpanel.net/cpanel/software/application-manager/).

## Private Paper Backend

Install `requirements.txt` in a server virtual environment. Keep source, data,
logs, and `.env` outside the public document root. Configure server-only values:

```dotenv
TRADING_MODE=paper
BOT_PROFILE=web-paper
WEB_USERNAME=<private username>
WEB_PASSWORD=<unique random password, at least 16 ASCII characters>
DATA_DIR=<absolute path to a private persistent data directory>
LOG_DIR=<absolute path to a private log directory>
WEB_ALLOWED_ORIGINS=https://trade23.futoltech.com
WEB_ENABLE_CYCLES=false
```

No credentials belong in `VITE_*` variables, browser storage, public ZIP files,
or Git. Blank/short web credentials prevent startup. All API routes require
authentication; use HTTPS online and add reverse-proxy login rate limiting.
The web UI holds credentials only in memory and clears them on sign-out/reload.

Run **one** worker with a process supervisor:

```sh
uvicorn bot.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Proxy HTTPS `/api` requests to that process. For a managed service that provides
TLS termination, bind as that service requires; the Render template uses its
assigned port. Set `DATA_DIR` to mounted persistent storage, not ephemeral
deployment files. Do not use a sleeping/free instance as a promise of reliable
24/7 trading or durable history.

Do not run a desktop bot, CLI bot, multiple API workers, or multiple replicas
against the same directory. Locks serialize requests inside this one API
process, not independent processes. Start a separate empty web paper account;
copying the desktop's active files while trading is running is not supported.

## Frontend on cPanel

Build in `web` using its existing package lock:

```sh
npm ci
npm run build
```

Default API URL is same-origin `/api`. With a separate backend, set
`VITE_API_URL=https://<verified-backend-host>/api` **before** building and set
`WEB_ALLOWED_ORIGINS` on that backend to the exact frontend origin.

Create `trade23.futoltech.com` with its own document root and provision SSL.
Back up its existing files. Upload only the contents of `web/dist`, including
the `.htaccess` SPA routing file. Do not upload this whole repository, local
`.env`, desktop EXE, logs, personal positions, or transaction history.

## Scheduled Paper Cycles

The API does not run a background trading loop. Reading or refreshing the
dashboard never opens trades. Its prices are cached marks from the latest
completed engine cycle, not a streaming quote feed. P2P remains desktop-only
in this web draft; do not present the website as full desktop feature parity.

Enable `WEB_ENABLE_CYCLES=true` only after the private persistent account,
single-worker ownership, and paper settings have been verified. Configure
exactly one scheduler to POST `/api/cron/run_cycle`, with HTTP Basic auth from a
private credential file. GET is rejected. Keep credential files outside web
roots, restrict their permissions, avoid credentials in shell command lines,
and do not overlap cron with a separate bot loop. Set an HTTP timeout and
monitor non-2xx responses; a cron entry is not a guarantee of reliable fills.

## Verification and Rollback

1. Confirm DNS and valid HTTPS at the requested subdomain.
2. Confirm assets, `/app`, `/app/history`, and `/app/settings` load.
3. Verify unauthenticated API reads/POSTs return 401 and invalid passwords fail.
4. Verify authenticated figures, net P&L units, and empty new account history.
5. Verify remote cycles are disabled initially and no GET opens trades.
6. Restart the backend and verify its persistent account/history survives.
7. Verify the existing `futoltech.com` site is unchanged.

If checks fail, restore only the backed-up subdomain release and stop its
paper scheduler. Do not replace private data with old release files.

Local checks: `python -m pytest tests/test_api.py -q` and `npm run build`.
