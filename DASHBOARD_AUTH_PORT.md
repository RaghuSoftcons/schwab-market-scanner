# Market Scanner — Dashboard Auth Port (from nt-bridge-v2)

**Date:** 2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
**Done in:** the "George's Automation" thread (which has the nt-bridge-v2 auth history), applied here.
**Purpose for the other thread:** this documents exactly what was ported into the Market Scanner so you
can review, test, and deploy it. The headline change is **multi-trader dashboard login** (so Vara/Dhanu can
sign in and the internet-facing scanner is protected), mirroring what was built for the nt-bridge trading
dashboard.

---

## What was ported ✅ (login/auth)
Same design as nt-bridge-v2: stdlib-only (pbkdf2 password hashing + HMAC-signed session cookies), a
file/env user store, an auth middleware, and login routes. **OFF by default** — local behavior is unchanged
until you set `DASHBOARD_AUTH_ENABLED=true` (intended for Railway).

**Files added:**
- `nt_schwab_bridge/auth.py` — the auth engine (copied from nt-bridge-v2, login page retitled "Schwab
  Market Scanner"). pbkdf2 hashing, signed sessions, `UserStore`, `AuthConfig.from_env()`, `render_login_html`,
  `verify_machine_key`, `current_trader` contextvar.
- `scripts/manage_users.py` — `set`/`list`/`remove`/`print-env`. Prompts for the password locally (getpass),
  hashes it, writes the **gitignored** `.local_state/dashboard_users.json`. Passwords are never committed/printed.
- `scripts/setup_dashboard_auth.ps1` — one-shot: seed raghu/vara/dhanu, generate the session secret, print the
  three Railway values.
- `tests/test_auth.py` — 8 unit tests (password, session, user store, machine key, config).

**Files changed:**
- `market_scanner/app.py`
  - Imports: added `Request`, `JSONResponse`, `RedirectResponse`, and the `nt_schwab_bridge.auth` symbols.
  - After `app = FastAPI(...)`: module-level `_auth_config`, `_user_store`, an `@app.middleware("http")`
    enforcer, and routes `GET/POST /login`, `GET /logout`, `GET /whoami`.
- `market_scanner/dashboard.py`
  - Script: a `window.fetch` wrapper that bounces to `/login` on any 401, and a `/whoami` call that shows
    "Signed in: <name> · Logout" only when auth is enabled.
  - Header: a `#whoami-chip` span + `#logout-button` link in `.top-actions` (hidden unless auth on).

## How enforcement works
- When `DASHBOARD_AUTH_ENABLED=true`, **every** request needs a valid session cookie EXCEPT the open paths:
  `/health`, `/login`, `/logout`, `/favicon.ico`, `/automation/kill` (keyed).
- **Machine callers keep working:** a request carrying the existing shared **`X-API-Key`**
  (`settings.service.api_key`, i.e. `SCANNER_API_KEY` / `GPT_ACTION_API_KEY`) bypasses the session check.
  So GPT actions and the dashboard's existing protected POSTs are unaffected; only **browsers** must log in.
- Browser page loads without a session → 303 redirect to `/login`; API calls → 401 (the dashboard JS then
  redirects). **Fails CLOSED**: enabled without `DASHBOARD_SESSION_SECRET` → 503 (never serves open).
- The existing `_require_api_key` dependency on POSTs is untouched (defense in depth).

## Verified (2026-07-01)
- Existing scanner suite: **117 passing** before, **125 passing** after (8 new auth tests). No regressions.
- End-to-end login flow (fresh app with auth on): health open (200); dashboard no-login → 303; `/schwab/status`
  no-login → 401; with `X-API-Key` → 200 (machine bypass); correct login → 303 + cookie → dashboard 200;
  `/whoami` → the trader; wrong password → `/login?error=1`. All as expected.

## To ACTIVATE on Railway (schwab-market-scanner)
1. Seed passwords locally: `python scripts/setup_dashboard_auth.ps1` (or `scripts/manage_users.py set ...`),
   then copy the printed `DASHBOARD_USERS_JSON` blob (hashes only) + the generated secret.
2. On the Railway service set:
   - `DASHBOARD_AUTH_ENABLED=true`
   - `DASHBOARD_SESSION_SECRET=<the secret>`
   - `DASHBOARD_USERS_JSON=<the blob>`   (or put the file on a volume as `DASHBOARD_USERS_FILE`)
   - leave `DASHBOARD_COOKIE_SECURE` default (true; Railway is HTTPS)
   - `SCANNER_API_KEY` / `GPT_ACTION_API_KEY` unchanged (machine bypass).
3. Redeploy → the dashboard URL now shows a login page. Vara/Dhanu use their username + password.

## NOT ported / follow-ups
- **Per-trader attribution.** nt-bridge stamps the acting trader on its order-audit via `current_trader`.
  The scanner's order/trade path differs (`market_scanner/orders.py`, `trade_log`); the `current_trader`
  contextvar is set by the middleware and ready, but it is **not yet stamped** into the scanner's records.
  Wire it in if you want who-placed-what on the scanner.
- **Login-flow automated tests.** The scanner `app` is a module-level singleton, so per-test env reconfig is
  awkward; the flow is unit-tested at the module level + verified manually here, and TestClient-tested in
  nt-bridge-v2. Consider refactoring to a `create_app()` factory if you want in-suite flow tests.
- **Other nt-bridge-v2 changes considered but N/A to the scanner:** signal relay (no NT signals), the
  trailing-arm give-up fix (no trailing), Open-Positions column reorder (scanner's positions panel differs —
  apply the same Strategy/Qty/Avg/Mark/Target/Stop order if you want visual consistency).
- **Token-authority consumer mode** was already applied to the scanner earlier (Codex); no change here.

## Reference
Mirror of nt-bridge-v2: `Unified Trading Platform with Schwab/nt-bridge-v2/` — `nt_schwab_bridge/auth.py`,
`RAILWAY_DEPLOYMENT_PLAN.md` §7A (multi-trader), and the auth tests there.
