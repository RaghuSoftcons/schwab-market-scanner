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

#### Phase 2b — Stop-management CONTROLS (mode + trail) — pending, low-risk UI
- Add `#stop-mode-select` (fixed/breakeven/trailing/be_then_trail) + `#trail-start`/`#trail-distance`/
  `#trail-poll`. Backend `dashboard_settings.py` already has `get/set_stop_mgmt`; carry into `appState`.
- **Blocked-until-2c to be useful:** without the monitor these persist a preference but don't act, so DON'T
  ship them live-looking until 2c — or gate/label them "arms once trailing monitor ships."

#### Phase 2c — Trailing MONITOR (the big backend port) — pending, needs live-verify
- Port Unified's arm loop + OCO cancel-then-place (`_arm_account_stop`, `_build_arm_oco_payload`,
  `_stop_replacement_payload`, the give-up/transient logic) so stop-mode/trail actually arm on the scanner.
- Live-verify like the Unified fix (cross +Start% → armed → real TRAILING/BE stop → exits above BE).
- Deprioritized per Raghu ("we can re-visit TS issues"); schedule as its own focused pass.

### Phase 3 — Proposal card parity
- Add legs display, the dark TOS order line + **Copy** button, and the **Exit Plan** section with a
  per-target **Send** button (target/OCO), plus account-routing rows with green/red **balance badges** and
  the quantity segmented control — matching Unified's `.proposal` markup/classes.
- Add the exit-send endpoint(s) the buttons call (mirror Unified's `.../targets/{i}/send`), or map to the
  scanner's existing order path.
- Tests: card renders all sections; exit-send hits the right endpoint.

### Phase 4 — Custom confirmation modal + Open Positions columns
- Port `customOrderConfirm()` + `.confirm-overlay`/`.confirm-box` and use it for every LIVE send/close
  (replace inline notice + native `confirm()`).
- Reorder/extend the Open Positions table to `Account·Symbol·Strategy·Qty·Avg·Mark·Target·Stop·UR·P/L%·Close`
  with sticky Close and the same sort keys.
- Tests: modal gating; positions header/rows order + P/L% math.

### Phase 5 — Optional polish
- Reversal banner (`#reversal-banner` + countdown + confirm/dismiss) if the scanner emits reversals.
- Richer audio (sound ready/mute/test + spoken "SYMBOL Side Indicator" phrase).

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
