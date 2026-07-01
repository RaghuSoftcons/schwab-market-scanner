# Market Scanner ← Unified Dashboard: Look-&-Feel + Order-Entry Parity Plan

**Date:** 2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
**Goal:** make the Market Scanner dashboard match the Unified (nt-bridge-v2) dashboard — "same approach"
for SL, OCO/OTOCO, targets, entry offset, stop-management, proposal card, positions panel, and the send flow.
**Approach chosen by Raghu:** full match, one planned pass (this doc), executed phase by phase in this thread.

---

## KEY INSIGHT (from mapping both dashboards)
The two dashboards **already share the same visual theme** — identical CSS variables (`--bg:#f4f6f8`,
`--panel:#fff`, `--ink:#17202a`, `--teal/--blue/--amber/--red/--green`, same `--shadow`), same fonts
(Segoe UI / Consolas), same segmented-button + panel styling. So this is **~10% visual, ~90% functional**:
the Scanner's order-entry controls mostly EXIST but are **frontend-only (localStorage, query-params) and
don't reliably drive the order payload**, and it's **missing the SL%/stop-management stack, a durable
settings backend, per-target exit sends, and the confirmation modal.**

## GAP TABLE (Unified = target behavior)
| Area | Unified (nt-bridge) | Scanner today | Work |
|---|---|---|---|
| Settings persistence | durable store + `GET/POST /dashboard/settings` | localStorage + query params only | **Port `dashboard_settings.py` + endpoints** |
| Stop-loss % | `#stop-loss-buttons` (0/20/25/30/40/50/60/70/80), drives payload | **absent** | **Add selector + wire to close/OCO** |
| Stop management | stop-mode (fixed/BE/trailing/be_then_trail) + trail start/dist/poll | **absent** | **Add controls + carry into stop_mgmt** |
| OTOCO toggle | drives bracketed-slice payload | checkbox is localStorage-only, no payload effect | **Wire to order payload** |
| Target %s | presets + inputs, honored on rebuild + per-target exit sends | inputs sent as query param but ignored on rebuild | **Honor on build + add per-target exit send** |
| Entry offset | 0–50¢, applied to entry limit | query param, only at build time | **Apply consistently to entry limit** |
| Proposal card | score badge, legs, TOS line + Copy, Exit Plan (per-target Send), account routing + balance badges, qty | score badge, compact order lines, inline send, no per-target exit send | **Add legs, Copy-TOS, Exit-Plan sends, balance badges** |
| Send confirm | custom modal `customOrderConfirm()` / `.confirm-overlay` | inline `.notice`, native `confirm()` for close | **Port the modal** |
| Open Positions | Account·Symbol·**Strategy·Qty·Avg·Mark·Target·Stop·UR·P/L%**·Close, sticky Close, sortable, Tracked/All | Account·Symbol·Target·Stop·Qty·Avg·Mark·UR·Close (no Strategy, no P/L%, old order) | **Add Strategy + P/L%, reorder, sticky Close** |
| Reversal banner | `#reversal-banner` + countdown + confirm/dismiss | absent | **Optional (Phase 5)** |
| Audio | sound ready/mute/test + spoken phrase ("NQ Short Aurora") | beep + speak "Long/Short" | **Optional enrich (Phase 5)** |

---

## PHASED EXECUTION PLAN
Each phase is self-contained, tested, and leaves the dashboard working. Reference source files live in
`Unified Trading Platform with Schwab/nt-bridge-v2/nt_schwab_bridge/` (`dashboard.py`, `dashboard_settings.py`,
`app.py`).

### Phase 1 — Durable settings backend (the backbone) — ✅ DONE 2026-07-01
Everything else depends on settings that persist and actually reach the order builder.
**Done:** brought the vendored `nt_schwab_bridge/dashboard_settings.py` to full parity (added OTOCO,
stop-management/trailing, entry-offset `0`); added `_dashboard_settings` store + `GET /dashboard/settings`
and `POST /dashboard/settings` (partial update, 422 on bad values, `_require_api_key` on POST) to
`market_scanner/app.py`; SL defaults to 50 + entry-offset to 0 (Unified parity). Store persists to gitignored
`.local_state/dashboard_settings.json`. Tests: `tests/test_dashboard_settings.py` (3); **suite 128 passing**.
Next: Phase 2 wires the dashboard controls to these endpoints and makes them shape the order payload.
- Port `nt_schwab_bridge/dashboard_settings.py` (DEFAULTS + choice lists + store) into the scanner (its
  vendored `nt_schwab_bridge/` already exists — add it there; the scanner's `.local_state/` is gitignored).
- Add `GET /dashboard/settings` + `POST /dashboard/settings` to `market_scanner/app.py` (partial update,
  normalized), backed by a `DashboardSettingsStore` on `.local_state/dashboard_settings.json`.
- On startup force `stop_loss_percent = 50` (never carry "No SL"), like Unified.
- Tests: settings round-trip, SL-reset-on-load, choice validation.

### Phase 2 — Order-entry controls parity (SL % + stop management + wiring)

**Correction discovered during Phase 2 (2026-07-01):** the scanner send is already OTOCO-capable —
`send_proposal` accepts `target_percentages` + `stop_loss_percent` and calls `_schwab_otoco_entry_payloads`.
Settings are **client-side localStorage + query params** (`appState.settings` → `sendProposal` URL), NOT the
server store, and there is **no trailing monitor** in the scanner backend at all. So Phase 2 splits:

#### Phase 2a — SL% selector, wired end-to-end — ✅ DONE 2026-07-01
- Added `#stop-loss-buttons` (0/20/25/30/40/50/60/70/80, default 50) to the settings bar; `setStopLoss` +
  `stopLossPercent`/`stopLossChoices` in `appState.settings` (localStorage, settingsVersion→5 migration).
- **Fixed a latent bug:** `sendProposal` sent only `target_percentages`; it now also sends
  `&stop_loss_percent=`, so the chosen SL% actually reaches the OTOCO stop (was always the default constant).
- Confirmation line shows the SL ("SL 50% below entry"). Tests: `tests/test_sl_selector.py` (3). Suite 133 ✅.

#### Phase 2b — Stop-management CONTROLS (mode + trail) — ✅ DONE 2026-07-01
- Added `#stop-mode-select` (fixed/breakeven/trailing/be_then_trail) + `#trail-start`/`#trail-distance`/
  `#trail-poll` to the settings bar; `appState` fields (stopMode/trailStartPct/trailDistancePct/trailPollSecs,
  defaults from `DEFAULT_STOP_MGMT`: be_then_trail/10/8/4), v6 migration. Trail fields grey out for Fixed SL.
- LIVE confirmation prints the active management ("at +10% profit, stop → breakeven then trails 8%").
- Backed by 2c below, so the controls actually act (not dead UI).

#### Phase 2c — Trailing MONITOR (the backend port) — ✅ CODE-COMPLETE 2026-07-01 · ⏳ needs live-verify
- New `market_scanner/trailing.py` (dependency-injected, fully unit-tested): payload builders
  (breakeven STOP, native TRAILING_STOP, arm-OCO, fixed-OCO restore), `resting_oco_for_symbol`,
  `confirm_orders_cleared`, `arm_account_stop` (cancel→confirm→place with restore-on-failure +
  transient/`_TrailArmRejected` taxonomy + 3-strike give-up), and `evaluate_trailing_arms`.
- `app.py`: `_registration_stop_mgmt` freezes intent at send (single-leg OTOCO + real stop + non-fixed);
  `stop_mgmt` stored on the tracked position; `_trailing_monitor_loop` added to the lifespan (adaptive
  cadence: `trail_poll_seconds` when pending, 30s idle; only acts when the live gate is open); send URL
  carries `stop_mode`/`trail_start_percent`/`trail_distance_percent`.
- Tests: `tests/test_trailing.py` (18) + `tests/test_registration_stop_mgmt.py` (5). Suite 156 ✅.
- **STILL NEEDS LIVE-VERIFY** (market was closed): a single-leg position crosses +Start% → armed →
  resting fixed STOP replaced by a real BE/TRAILING stop → exits above breakeven. Do during market hours.

### Phase 3 — Proposal card parity — ✅ ALREADY AT PARITY (no rewrite) 2026-07-01
- Audit found the scanner card already has every substantive element: legs display, dark TOS order line +
  **Copy TOS** + **Send to Schwab**, the **Exit Plan** section (per-target **Copy SELL** / **Send SELL** +
  Get-Order-Info status), the **quantity control**, score circle, GEX walls, score breakdown, and
  **account-routing rows with green/red balance badges**. The exit-send endpoints already exist
  (`.../targets/{i}/send`). Only cosmetic class-name differences remain (`proposal-top` vs `proposal-main`).
- **Decision:** a class-name rewrite of a working 2000-line card is high-risk / low-value churn, so Phase 3
  is treated as done-at-parity. No code change.

### Phase 4 — Open Positions parity (Target/Stop/trailing/P&L%) — ✅ DONE 2026-07-01
- The scanner already had **Target** + **Stop** columns (`_target/_stop_prices_for_orders`) and a **Close**
  button. Ported the genuine gap — the **armed-trailing display** (Unified 5b): `_stop_prices_for_orders`
  now recognizes `TRAILING_STOP` and emits a `('trail', offset)` marker; `_resolve_stop_marker` turns it into
  the effective trigger (mark − offset) + `stop_trailing`/`stop_trail_offset` on `PositionRow`; the Stop cell
  shows `<price> ⤴<offset>` so an armed trail never blanks. This is the visible payoff of the 2c monitor.
- Added a **P/L %** column (derived from avg/mark, sortable). `customOrderConfirm` modal was NOT ported — the
  scanner's native `confirm()` is functional and the custom overlay is cosmetic (skipped to avoid churn).
- Tests: `tests/test_trailing_stop_display.py` (6). Suite 162 ✅.

### Phase 5 — Polish — ✅ DONE (applicable parts) 2026-07-01
- **Spoken alert upgraded** to the Unified convention: the top-candidate voice now says
  "`<SYMBOL> <Side>`" (e.g. "D I A Long") instead of just "Long"/"Short", with short all-caps tickers
  spelled letter-by-letter (`spokenSymbol`). Mute + audio cue already existed.
- **Reversal banner intentionally NOT ported:** the Unified banner is driven by the NT8 opposite-signal
  stream; the scanner scans candidates and has no live reversal-signal source, so the banner would be dead
  UI. `close_on_reversal` remains a setting. Skipped by design.

---

## NOTES / CONSTRAINTS
- The scanner `app` is a **module-level singleton** (not `create_app()`); a factory refactor would help
  testing but isn't required — settings/endpoints can be module-level like the rest.
- Keep the existing shared **X-API-Key** machine path and the new **login** (both already in place).
- Do NOT change the scanner's execution gates / triple-lock; match Unified's *approach*, not looser gates.
- Deploy: this folder isn't a git repo locally — code reaches Railway via whatever the scanner builds from
  (confirm with Raghu). See `DASHBOARD_AUTH_PORT.md`.

## Change Log
- 2026-07-01  Plan written from side-by-side dashboard maps (Claude + Raghu).
- 2026-07-01  Phase 2 corrected + split (2a/2b/2c). Phase 2a (SL% selector wired end-to-end + send-bug fix)
              DONE; tests 133 green. 2b/2c (stop-management controls + trailing monitor) scoped, deferred.
