# Market Scanner ⟵ Unified Platform: Enhancement Porting Plan

**File:** PORTING_PLAN_Claude_2026-06-22.md
**Created:** 2026-06-22 11:55 EST
**Author:** Claude (Anthropic) + Raghu
**Version:** 1.3.0
**Last Modified:** 2026-06-22 13:20 EST

**Change Log:**
- 2026-06-22 11:55 EST | 1.0.0 | Initial porting proposal + new-thread prompt.
- 2026-06-22 11:58 EST | 1.1.0 | Full scope per Raghu: automation tiers (#7) and GEX wall exits (#8) promoted from optional to in-scope; GEX wired to feed the OCO target/stop.
- 2026-06-22 13:06 EST | 1.2.0 | Added enhancement #11: Open Positions panel + dashboard closing (manual Close-now + Close-on-Reversal), built in the bridge this session. Motivated by the SMCI case — the scanner placed SMCI calls across 4 accounts with no dashboard position view or close. Added Phase 6 and prompt item 9.
- 2026-06-22 13:20 EST | 1.3.0 | Expanded prompt item #3 (margin/cash balance fix) to include the current-vs-projected nuance + `_conservative_available` helper (Individual account showed $521.87 current vs $170.54 projected, which is what Schwab displays). Synced canonical + this "Market Scanner Updates by Claude" working copy.

---

## TL;DR

The **Schwab Market Scanner** (`D:\Google Drive\0.00 ChatGPT Codex\Schwab Market Scanner`,
FastAPI on **port 5002**) and the **Unified Trading Platform** (`...\Unified Trading
Platform with Schwab\nt-bridge-v2`, port **6001**) **share the same internal library:
`nt_schwab_bridge/`.** The scanner carries an **older vendored copy**; the Unified
Platform's copy is the one we enhanced. So most of the "duplication" the user wants is
really **(a) refreshing the scanner's `nt_schwab_bridge` to the enhanced version, then
(b) wiring the scanner's own glue files to call the new capabilities.**

Two architectures, same broker, same token file (`D:\data\schwab\schwab_tokens.json`).

---

## What the scanner has today

- Gap-up/gap-down scan of an equity universe (SPY/QQQ/DIA regime + AAPL/NVDA/JPM candidates).
- Builds **single-leg CALL/PUT + debit-vertical** proposals from live Schwab chains.
- **Proposal-first, gated execution:** triple-lock (`SCANNER_EXECUTION_MODE=live` +
  `SCANNER_ALLOW_LIVE_ORDERS=true` + `SCANNER_TRADING_ENABLED=true`) + per-request
  `confirm_live_order=true`.
- Submits **entry** orders (`LIMIT` single / `NET_DEBIT` vertical). **Exit targets are
  sent as separate `NET_CREDIT` orders AFTER fill — there is NO OCO/bracket today.**
- Embedded HTML/JS dashboard (`dashboard.py`), polling, no audio, no per-account P&L.
- **No open-positions view and no way to close a trade from the dashboard.** Once an order is
  sent (incl. multi-account scalps like the SMCI 6/26 calls placed across 4 accounts), the only
  place to see or close it is Schwab/thinkorswim. This is the gap enhancement #11 fixes.
- Local Schwab **auto-refresh ON** (its own refresher — this is the token-rotation race risk).
- pytest suite (`test_scanner_logic`, `test_dashboard`, `test_order_status`).

## What the Unified Platform added (the enhancements to port)

| # | Enhancement | Where it lives | Ports cleanly to a STOCK scanner? |
|---|---|---|---|
| 1 | **OCO exit orders** (entry + `OCO` child target/stop) | `app.py` order builders | ✅ Yes — top priority |
| 2 | **token-service consumption** (read-only; kill local refresh → no rotation race) | `token-service/`, `schwab_adapter.py` | ✅ Yes — high value |
| 3 | **Per-account realized P&L sync** (Schwab transactions, dedup-by-symbol, aliases) | `pnl_sync.py`, `dashboard_stats.py` | ✅ Yes |
| 4 | **Account discovery + margin/cash balance fix** (availableFunds for margin, cashAvailableForTrading for cash) | `schwab_adapter.py` `_extract_account_balance_summary` | ✅ Yes — small, do early |
| 5 | **Score breakdown UI** (sub-components as value/max e.g. 36/40, enrichment row) | `dashboard.py`, `planner.py` | ✅ Yes (adapt to gap-score inputs) |
| 6 | **Dashboard polish:** mute button, audio "Long"/"Short", cursor-follow card, brighter selection | `dashboard.py` | ✅ Yes |
| 7 | **Risk rails / automation tiers** (Tier 1 manual → Tier 3 autopilot w/ cancel window) | `automation.py`, `decision.py` | ✅ In scope — layers on top of the existing triple-lock |
| 8 | **GEX wall exits** (gamma walls → target/stop, capped at max-loss) | `gex.py`, `gex_exits.py` | ✅ In scope — feeds the OCO target/stop; falls back to $/% when gamma is thin |
| 9 | **Order-flow confirmation** (OCM footprint +15/-20, volume filter) | `orderflow.py` | ❌ **Does NOT apply** — footprint feed is futures-only; scanner trades single stocks with no footprint snapshot. Skip. |
| 10 | **Futures→ETF symbol mapping** (ES→SPY …) | `config.py` symbol_map | ❌ N/A — scanner trades equities directly |
| 11 | **Open Positions panel + dashboard closing** — live positions view, per-position **Close now** (cancel resting order + MARKET close), optional Close-on-Reversal | `app.py` (`/active-positions`, `/active-positions/{symbol}/close`, `_market_close_position`, `_try_close_on_reversal`), `dashboard.py` (panel + Close-now button), `dashboard_settings.py` (`close_on_reversal`), `schwab_adapter.py` (add `get_positions`) | ✅ **In scope — the SMCI gap.** Use the AUTHORITATIVE Schwab-positions pull (not the bridge's in-memory tracker) since the scanner places trades directly across accounts. |

---

## Recommended approach & sequencing

**Strategy: diff-merge the shared package, then wire the glue.** Do NOT blind-copy the
Unified Platform's `nt_schwab_bridge` over the scanner's — the two `app.py`/`dashboard.py`
have diverged and a blind overwrite would break the scanner. Instead, port the
**self-contained modules** (which the scanner doesn't customize) wholesale, and
**hand-merge** the shared files the scanner depends on.

**Phase 0 — Safety net (do first)**
- Snapshot the scanner folder to `_Backups\Schwab Market Scanner\` (timestamped).
- Confirm both stacks point at the same token file; get the scanner's tests green as a baseline.

**Phase 1 — Token-service consumption (#2, #4)** — highest leverage, lowest UI churn
- Set scanner `SCHWAB_AUTO_REFRESH_ENABLED=false`; consume tokens read-only from the shared
  file / token-service `GET /token`. This removes the refresh-token rotation race that has
  bitten the platform repeatedly.
- Port the margin/cash `_extract_account_balance_summary` fix (already done in the platform).

**Phase 2 — OCO exit orders (#1)** — the headline feature the user asked for
- Replace the "separate NET_CREDIT after fill" exit path with a true bracket: entry order,
  then `orderStrategyType: "OCO"` with `childOrderStrategies: [LIMIT target, STOP stop]`.
- Keep all existing triple-lock gates. Stops/targets from scanner's own max-loss/target %
  config (the scanner has no GEX yet — dollar/percent-based is fine).

**Phase 3 — Per-account P&L (#3)** — port `pnl_sync.py` + dashboard P&L rows + aliases.

**Phase 4 — Dashboard polish (#5, #6)** — score breakdown value/max, mute, audio Long/Short,
cursor-follow card.

**Phase 5 — Automation tiers (#7) + GEX wall exits (#8)** — in scope. Land GEX after OCO
(Phase 2) since GEX feeds the OCO target/stop; tiers last since they sit on top of a
working, tested order path.

**Phase 6 — Open Positions panel + dashboard closing (#11)** — the SMCI gap. Build it after
OCO (Phase 2) so the **Close now** button has resting orders to cancel/replace. For a stock
scanner, use the **authoritative Schwab-positions pull** (`get_positions` →
`/accounts/{hash}?fields=positions`) so directly-placed and multi-account trades show up — the
bridge's in-memory tracker would miss them. Then port the per-position **Close now** (cancel
resting order + MARKET close, behind the triple-lock + a confirm()) and, optionally, the
Close-on-Reversal toggle (lower priority for a re-scanning scanner; ship the toggle OFF until
validated).

**Explicitly out of scope:** #9 order-flow footprint (futures-only) and #10 futures→ETF
mapping (scanner trades stocks).

## Key risks
- **Package divergence:** the scanner's vendored `nt_schwab_bridge` may lag the platform's
  in `models.py`/`config.py`/`schwab_adapter.py`. Merge module-by-module with the scanner's
  test suite as the gate after each step.
- **Live-order safety:** never relax the triple-lock during the port; OCO changes the order
  payload, so dry-run-print and eyeball the JSON before any live submit.
- **Two dashboards, one look:** the scanner dashboard is its own file; UI features must be
  re-implemented against the scanner's data shape, not copy-pasted.

---

## PROMPT FOR THE NEW THREAD (copy everything below this line)

---

You are porting recent enhancements from the **Unified Trading Platform with Schwab**
into the older **Schwab Market Scanner**. Both are FastAPI apps that share an internal
`nt_schwab_bridge/` library; the scanner carries an OLDER vendored copy.

**Folders**
- Target (port INTO): `D:\Google Drive\0.00 ChatGPT Codex\Schwab Market Scanner` (port 5002)
- Source (port FROM): `D:\Google Drive\0.000 Claude Code\Unified Trading Platform with Schwab\nt-bridge-v2` (port 6001) and its `..\token-service` (port 5055)
- Shared token file: `D:\data\schwab\schwab_tokens.json`

**Global rules (from CLAUDE.md):** start/end every response with the EST timestamp line;
add a file header + Change Log to every new/modified source file; back up any changed
scanner files to `D:\Google Drive\0.000 Claude Code\_Backups\Schwab Market Scanner\` with a
timestamped filename before overwriting. PowerShell/Bash are pre-approved.

**Hard safety rules:** Do NOT relax the live-order triple-lock
(`SCANNER_EXECUTION_MODE` + `SCANNER_ALLOW_LIVE_ORDERS` + `SCANNER_TRADING_ENABLED`) or the
per-request `confirm_live_order`. Do NOT perform interactive Schwab OAuth/browser login or
enter any credentials — the token-service owns refresh. Dry-run-print and visually verify
every new order JSON before any live path. Keep the scanner's pytest suite green after each phase.

**Start by** reading the scanner's `market_scanner/app.py`, `orders.py`, `dashboard.py`,
`config.py`, and its vendored `nt_schwab_bridge/{schwab_adapter,planner,models,config}.py`,
then diff against the same files in the Unified Platform to find the divergence. Present a
short confirmation of the plan before editing.

**Port these, in order (the two items under "Do NOT port" at the end are out of scope):**

1. **OCO exit orders (headline):** replace the scanner's "separate NET_CREDIT exit after
   fill" with a true bracket — entry order, then `orderStrategyType:"OCO"` with
   `childOrderStrategies:[LIMIT profit-target, STOP stop-loss]`. Base target/stop on the
   scanner's existing max-loss and target-% settings. Reference the Unified Platform's OCO
   builder in its `app.py` (search `"OCO"` / `childOrderStrategies`).
2. **Token-service consumption:** set the scanner to read tokens read-only
   (`SCHWAB_AUTO_REFRESH_ENABLED=false`) and consume from the shared file / token-service
   `GET /token`, eliminating its independent refresh (which races and invalidates the
   rotating refresh_token). Mirror the platform's read-only token consumption in `schwab_adapter.py`.
3. **Margin/cash balance fix:** port `_extract_account_balance_summary` + the
   `_conservative_available` helper so MARGIN accounts use `availableFunds` and CASH accounts
   use `cashAvailableForTrading`, AND it takes the **minimum of current vs projected** for the
   chosen metric (projected nets out pending/unsettled buys — e.g. the Individual account
   showed $521.87 current but Schwab displays $170.54 projected). Copy the logic + its tests.
4. **Per-account realized P&L:** port `pnl_sync.py` (Schwab transactions → netted closes,
   dedup key INCLUDING `option_symbol` so vertical legs don't collide, 14-day lookback) and
   surface per-account P&L rows with aliases on the scanner dashboard.
5. **Score breakdown UI:** show each proposal's score sub-components as value/max (e.g. 36/40)
   plus any enrichment row, adapted to the scanner's gap/volume/regime scoring inputs.
6. **Dashboard polish:** mute button (persist to dashboard settings), audio that speaks
   "Long"/"Short" with a beep, cursor-follow proposal card, brighter selection highlight.
7. **Automation tiers:** port Tier 1 (manual send) → Tier 2 (auto-queue high-score with a
   cancel window) → Tier 3 (autopilot, gated by RiskManager + the triple-lock). Reference
   `automation.py` / `decision.py`. All existing risk gates must still apply at every tier.
8. **GEX wall exits:** port the gamma-exposure logic (`gex.py`, `gex_exits.py`) so the
   OCO target/stop in #1 can be set from the call wall (target) and put wall (stop),
   ALWAYS hard-capped at the configured max-loss dollars. Use it for liquid single-name
   options where chain gamma data is available; fall back to the dollar/percent stops from
   #1 when gamma data is thin or missing.
9. **Open Positions panel + dashboard closing (the SMCI gap):** today the scanner can place an
   order (e.g. SMCI 6/26 calls across 4 accounts) but gives you NO way to see or close it from
   the dashboard — only Schwab/thinkorswim shows it. Build a position-management layer:
   (a) **Authoritative Open Positions panel** — add `get_positions(account_hash)` to
   `schwab_adapter.py` (`GET /trader/v1/accounts/{hash}?fields=positions`), a `/positions`
   endpoint aggregating across selected accounts, and a dashboard panel showing per-account
   symbol / qty / avg cost / mark / unrealized P&L, refreshed on a timer. For a stock scanner
   this authoritative pull is REQUIRED — an in-memory tracker would miss directly-placed and
   post-restart positions.
   (b) **Per-position "Close now"** — cancel the resting exit order(s) and submit a MARKET
   close. Reuse the platform's `_market_close_position` pattern (replace the resting OCO with a
   MARKET order, else cancel+place). Gate behind the live triple-lock + a JS `confirm()`; write
   an audit event. Reference the platform's `POST /active-positions/{symbol}/close`.
   (c) **Close-on-Reversal (optional, ship OFF):** port `_try_close_on_reversal` +
   the `close_on_reversal` setting so an open position auto-closes when the opposite signal
   fires for the same symbol/source. Lower priority for a re-scanning scanner — include the
   toggle but leave it OFF until validated.

**Do NOT port:** order-flow footprint confirmation (`orderflow.py` — futures-only feed,
no footprint for single stocks) and futures→ETF symbol mapping (scanner trades equities directly).

Work phase-by-phase, run the scanner tests after each, and dry-run the order JSON before
declaring a phase done.
