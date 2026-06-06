# Schwab Market Scanner

Railway-ready premarket/intraday scanner that reuses the working Schwab token and guarded order patterns from:

- `D:\Google Drive\0.00 ChatGPT Codex\ChatGPT to Schwab Integration CLEAN`
- `D:\Google Drive\0.00 ChatGPT Codex\NT to Schwab Integration`

## Current Railway Deployment

Project: `imaginative-growth`

Service: `schwab-market-scanner`

URL:

```text
https://schwab-market-scanner-production.up.railway.app
```

The deployed service is currently in dry-run mode with live order gates closed.

## What It Does

- Scans market regime through `SPY`, `QQQ`, and `DIA`.
- Scans a configured ticker universe every 30 minutes.
- Starts with two Monday test tickers:
  - `AAPL`
  - `NVDA`
- Ranks candidates by gap, premarket volume, and regime fit.
- Produces `CALL_BIAS`, `PUT_BIAS`, `WATCH`, or `AVOID`.
- Pulls Schwab option chains and builds proposal cards when a candidate has directional bias.
- Uses protected limit orders, not true market orders.
- Keeps live order submission behind explicit gates and per-request confirmation.

## Safety Gates

An order can be submitted only when all are true:

- `SCANNER_EXECUTION_MODE=live`
- `SCANNER_ALLOW_LIVE_ORDERS=true`
- `SCANNER_TRADING_ENABLED=true`
- the API request sets `confirm_live_order=true`
- a valid Schwab account is selected

Otherwise `/proposals/{proposal_id}/send` returns a dry-run or blocked result with the Schwab order payload for review.

## Shared Schwab Token

This project uses the same token shape and flow as the CLEAN Schwab project.

Local default:

```text
D:\data\schwab\schwab_tokens.json
```

Railway default:

```text
/data/schwab/schwab_tokens.json
```

You only need one Schwab refresh/login cycle. After refreshing through the CLEAN project, seed Railway with the same:

- `SCHWAB_ACCESS_TOKEN`
- `SCHWAB_REFRESH_TOKEN`
- `SCHWAB_ACCESS_TOKEN_EXPIRES_AT`
- `SCHWAB_TOKEN_STORE_PATH`
- `SCHWAB_CLIENT_ID`
- `SCHWAB_CLIENT_SECRET`

Helper for this Railway service:

```powershell
.\sync_schwab_to_railway_scanner.ps1 -DryRun
.\sync_schwab_to_railway_scanner.ps1 -RailwayService schwab-market-scanner
```

The helper does not print token values.

## Railway Variables

Minimum:

```text
SCHWAB_MARKET_DATA_ENABLED=true
SCHWAB_AUTO_REFRESH_ENABLED=true
SCHWAB_TOKEN_STORE_PATH=/data/schwab/schwab_tokens.json
SCHWAB_CLIENT_ID=...
SCHWAB_CLIENT_SECRET=...
SCHWAB_ACCESS_TOKEN=...
SCHWAB_REFRESH_TOKEN=...
SCHWAB_ACCESS_TOKEN_EXPIRES_AT=...
SCANNER_API_KEY=...
SCANNER_STORAGE_PATH=/data/scanner
```

Dry-run defaults:

```text
SCANNER_EXECUTION_MODE=dry_run
SCANNER_ALLOW_LIVE_ORDERS=false
SCANNER_TRADING_ENABLED=false
```

Ticker universe:

```text
SCANNER_SYMBOLS=AAPL,NVDA
SCANNER_REGIME_SYMBOLS=SPY,QQQ,DIA
SCANNER_INTERVAL_MINUTES=30
```

## Endpoints

- `GET /health`
- `GET /dashboard`
- `GET /schwab/status`
- `GET /accounts`
- `POST /scan/run`
- `POST /scan/replay`
- `GET /scan/latest`
- `POST /proposals/{proposal_id}/send`

Protected endpoints accept:

```text
X-API-Key: <SCANNER_API_KEY>
```

Replay Friday/current historical candles:

```powershell
Invoke-WebRequest -UseBasicParsing -Method Post `
  "https://schwab-market-scanner-production.up.railway.app/scan/replay?as_of=2026-06-05&save=true&simulate_options=true" `
  -Headers @{ "X-API-Key" = "<SCANNER_API_KEY>" }
```

If `as_of` is a date, the scanner replays that day at `09:29 America/New_York`.
If `as_of` is omitted, it replays the most recent weekday at 09:29.
Historical replay ignores live equity quotes. With `simulate_options=true`, it generates `SIM_ONLY` proposal cards from replayed underlying prices and current Schwab option-chain contract data. These proposals are blocked from Schwab order submission.

## Local Checks

```powershell
python -m pytest -q
python -c "from fastapi.testclient import TestClient; from market_scanner.app import app; c=TestClient(app); print(c.get('/health').json())"
```

Run locally:

```powershell
uvicorn market_scanner.app:app --host 127.0.0.1 --port 5002 --reload
```

Open:

```text
http://127.0.0.1:5002/dashboard
```

## Current Smoke Result

On Saturday, June 6, 2026, a read-only local Schwab scan succeeded after the shared token refreshed:

- Regime: bullish
- Candidates: `NVDA` and `AAPL` came back call-biased from the test universe
- Option proposals: correctly blocked because weekend option quotes were stale

That is expected. The scanner should produce order-ready proposals only when Schwab option-chain quotes pass freshness/liquidity filters during options hours.
