from __future__ import annotations

import json

# =============================================================================
# File: dashboard.py
# Created: (pre-existing)
# Author: Claude (Anthropic) + Raghu
# Version: 1.3.0
# Last Modified: 2026-06-22 15:22 EST
#
# Change Log
# -----------------------------------------------------------------------------
# 2026-06-22 15:22 EST  v1.3.0  VISUAL REBUILD to match the Unified Trading
#     Platform dashboard look (nt_schwab_bridge/dashboard.py): adopted the
#     Platform's CSS palette/typography/panel+badge+segmented styling, two-column
#     dashboard-layout, grouped "Platform" status panel (token/tier/win badges +
#     TOKEN/ORDERS/QUOTES/KILL row, Tier segmented control + Release/Refresh,
#     Enrich toggles [scoring + GEX exits only; order-flow N/A], P&L Today/Wk/Mo/
#     All row + Sync), LIVE/ORDERS LIVE/PLANNER/SCHWAB READY KPI badge strip, and
#     the rich proposal card with a confidence score circle alongside the existing
#     value/max score breakdown and GEX wall boxes. Top Candidates restyled like
#     the Platform's Recent Signals table (Scanner is gap-scan driven, so it maps
#     to the signal slot). ALL request/data/order logic preserved byte-for-byte:
#     every fetch URL, query param, JSON body and the SCANNER_API_KEY/authOptions
#     injection are unchanged; only RENDER (HTML-building) functions + markup were
#     restyled, plus DOM-only writes to populate the new Platform-panel elements.
# 2026-06-22 14:56 EST  v1.1.0  Added embedded-dashboard panels that call the
#     existing (tested) backend endpoints:
#       - Realized P&L panel (#4): GET /pnl/summary headline + per-account rows,
#         "Sync P&L" -> POST /pnl/sync.
#       - Open Positions panel + Close-now (#9): GET /positions (15s timer +
#         manual refresh), per-row "Close now" -> POST /positions/{symbol}/close
#         with confirm; surfaces blocked/dry_run per-account reasons.
#       - Automation panel (#7): GET /automation/status; tier buttons Off/1/2/3
#         (Tier 2/3 send confirm:true) -> POST /automation/tier; KILL ->
#         POST /automation/kill; Release kill -> POST /automation/kill/release.
#       - Dashboard polish (#6): persistent Mute (localStorage) + speech/beep
#         cue when a new top candidate appears; brighter selection highlight.
#       - OCO stop visibility (#1): exit targets now show Stop @X.XX and the
#         tos_stop_order_line when stop_trigger_price > 0.
#       - Score breakdown (#5): small "Gap .. / Vol .. / Regime .." line under
#         each candidate (fields present on candidate/scan JSON).
# 2026-06-22 16:10 EST  v1.2.0  Forced AUTO expiry on Build/Build All/Refresh
#     (dropdown change rebuilds the selected candidate on the chosen date). Block
#     notice/chip now name the specific reason. SECURITY: dashboard_html(api_key)
#     injects settings.service.api_key so authOptions attaches X-API-Key on every
#     protected POST; empty key keeps no-auth behavior unchanged.
# =============================================================================


def dashboard_html(api_key: str = "") -> str:
    # Inject the configured API key so the operator's browser can authenticate protected POSTs
    # when SCANNER_API_KEY is set. Empty key -> empty string -> authOptions sends no header
    # (the backend treats an unset key as no-auth, so behavior is unchanged when no key is set).
    # json.dumps yields a safe quoted JS string literal (handles quotes/backslashes/unicode).
    return _DASHBOARD_TEMPLATE.replace("__SCANNER_API_KEY__", json.dumps(api_key or ""))


_DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Schwab Market Scanner</title>
  <style>
    /* Visual language adopted from the Unified Trading Platform dashboard
       (nt_schwab_bridge/dashboard.py) so the Scanner matches it look-for-look.
       All request/data logic in the <script> block below is the Scanner's own. */
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dde5;
      --line-soft: #e6ebf1;
      --teal: #0f766e;
      --blue: #2563eb;
      --amber: #b45309;
      --red: #991b1b;
      --green: #166534;
      --green-bg: #e8f5ee;
      --amber-bg: #fff4df;
      --red-bg: #feecec;
      --navy: #111827;
      --shadow: 0 1px 2px rgba(17, 24, 39, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 "Segoe UI", Arial, sans-serif;
    }
    button, input { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      min-height: 30px;
      padding: 5px 9px;
      border-radius: 6px;
      cursor: pointer;
      box-shadow: var(--shadow);
    }
    button.primary { background: var(--green-bg); border-color: #b7dfc5; color: var(--green); font-weight: 700; }
    button.good { background: var(--green-bg); border-color: #b7dfc5; color: var(--green); font-weight: 700; }
    button.danger { color: var(--red); font-weight: 700; }
    button.ghost { background: var(--panel); }
    button.sound { border-color: #b7dfc5; background: var(--green-bg); color: var(--green); font-weight: 700; }
    button:disabled { color: var(--muted); cursor: not-allowed; opacity: 0.65; }
    button:focus-visible, .segment-button:focus-visible, .candidate-row:focus-visible {
      outline: 2px solid var(--blue); outline-offset: 2px;
    }
    input {
      border: 1px solid var(--line);
      background: white;
      border-radius: 6px;
      padding: 6px 9px;
      min-width: 200px;
      color: var(--ink);
    }
    .page { width: min(1440px, 100%); margin: 0 auto; padding: 8px; }
    .topbar {
      display: grid; grid-template-columns: 1fr auto; gap: 6px; align-items: center; margin-bottom: 6px;
    }
    .title h1 { margin: 0; font-size: 16px; font-weight: 700; letter-spacing: 0; }
    .title .sub { margin-top: 1px; color: var(--muted); font-size: 11px; }
    .top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .layout {
      display: grid;
      grid-template-columns: minmax(500px, 0.92fr) minmax(460px, 1.08fr);
      gap: 12px;
      align-items: start;
    }
    .layout > div { display: grid; gap: 6px; min-width: 0; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }
    .panel-head {
      display: flex; gap: 8px; align-items: center; justify-content: space-between;
      padding: 10px 12px; border-bottom: 1px solid var(--line);
    }
    .panel-head h2 { margin: 0; font-size: 13px; font-weight: 700; white-space: nowrap; }
    .panel-title { font-size: 13px; font-weight: 700; white-space: nowrap; }
    .panel-body { padding: 12px; }
    .candidate-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .candidate-actions button { padding: 4px 8px; font-size: 12px; min-height: 26px; }
    .build-cell { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
    .row-build { padding: 3px 8px; font-size: 12px; font-weight: 700; color: var(--blue); min-height: 24px; }
    .build-cell .badge { min-height: 22px; padding: 2px 7px; font-size: 11px; }
    .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0; }

    /* --- LIVE/ORDERS/PLANNER/SCHWAB badge metrics row (Platform "metrics") --- */
    .kpis {
      display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 8px; margin-bottom: 0;
    }
    .kpi {
      border: 1px solid var(--line); border-radius: 8px; padding: 7px 8px; min-height: 54px; background: #fbfcfe;
    }
    .kpi .value { margin-top: 2px; font-size: 16px; font-weight: 700; overflow-wrap: anywhere; }

    /* --- grouped Platform status panel --- */
    .platform-strip { font-size: 12px; color: var(--muted); }
    .platform-rows { padding: 7px 12px 9px; display: flex; flex-direction: column; gap: 5px; }
    .platform-row { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 14px; font-size: 12px; }
    .platform-row .label { font-size: 10px; }
    .platform-row b, .platform-row strong { font-weight: 700; }
    .ps-mode { color: var(--muted); font-size: 11px; }
    .flag-toggle { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; user-select: none; }
    .flag-toggle input { width: 14px; height: 14px; accent-color: var(--green); }

    .state-summary {
      padding: 9px 12px 11px; border-top: 1px solid var(--line); color: var(--muted);
      font-size: 12px; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .badges { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .badge {
      display: inline-flex; align-items: center; min-height: 24px; border-radius: 999px;
      padding: 3px 8px; font-size: 11px; font-weight: 700;
      border: 1px solid var(--line); background: #eef2f7; color: var(--ink); white-space: nowrap;
    }
    .badge.green { background: var(--green-bg); color: var(--green); border-color: #b7dfc5; }
    .badge.amber { background: var(--amber-bg); color: var(--amber); border-color: #f0d39a; }
    .badge.red { background: var(--red-bg); color: var(--red); border-color: #f2bcbc; }
    .badge.blue { background: #eaf1ff; color: var(--blue); border-color: #bfd2ff; }
    .badge.gray { background: #eef2f7; color: var(--muted); border-color: var(--line); }
    .notice {
      border-left: 4px solid var(--amber); background: var(--amber-bg); padding: 6px 10px;
      color: #6f4200; border-radius: 6px; overflow-wrap: anywhere; font-size: 12px; line-height: 1.4;
    }
    .notice.green { border-left-color: var(--green); background: #f0fbf5; color: #0b5c2f; }
    .notice.red { border-left-color: var(--red); background: var(--red-bg); color: var(--red); }

    /* --- candidate / signals tables --- */
    .table-wrap { overflow-x: auto; width: 100%; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    .table-wrap table { min-width: 100%; }
    th, td {
      text-align: left; padding: 8px 8px; border-bottom: 1px solid var(--line);
      vertical-align: middle; font-size: 13px;
    }
    th { color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; }
    tr.candidate-row { cursor: pointer; }
    tr.candidate-row:hover { background: #f0f7f6; }
    tr.candidate-row.selected { background: #c6ecd6; box-shadow: inset 4px 0 0 var(--green); }

    /* --- open positions table --- */
    .pos-table { width: 100%; border-collapse: collapse; font-size: 12px; table-layout: auto; }
    .pos-table th {
      text-align: left; color: var(--muted); font-weight: 700; font-size: 11px; text-transform: uppercase;
      padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap;
    }
    .pos-table th.num { text-align: right; }
    .pos-table th.sortable { cursor: pointer; user-select: none; }
    .pos-table th.sortable:hover { color: var(--ink); }
    .pos-table td { padding: 6px 8px; border-bottom: 1px solid var(--line-soft); white-space: nowrap; }
    .pos-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .pos-table td.mono { font-family: Consolas, "Courier New", monospace; font-size: 11px; white-space: normal; overflow-wrap: anywhere; }
    .pos-action { text-align: right; }
    .danger.small { padding: 2px 8px; font-size: 11px; min-height: 0; }

    /* --- score breakdown box (rich card; value/max) --- */
    .score-breakdown-box { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; margin: 8px 0; background: #ffffff; }
    .score-breakdown-box .sb-head { font-size: 11px; color: var(--muted); font-weight: 700; text-transform: uppercase; margin-bottom: 4px; }
    .sb-row { display: flex; justify-content: space-between; gap: 8px; font-size: 12px; padding: 2px 0; color: var(--muted); }
    .sb-row .sb-val { font-variant-numeric: tabular-nums; color: var(--ink); }
    .sb-total { border-top: 1px solid #e5e7eb; margin-top: 3px; padding-top: 4px; font-weight: 700; color: #111827; }

    /* --- GEX wall boxes --- */
    .gex-walls { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
    .gex-box { border-radius: 8px; padding: 7px 10px; }
    .gex-box .label { font-size: 10px; font-weight: 700; }
    .gex-box .value { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
    .gex-box.target { background: var(--green-bg); border: 1px solid #b7dfc5; }
    .gex-box.target .label, .gex-box.target .value { color: var(--green); }
    .gex-box.stop { background: #fdeeee; border: 1px solid #f2bcbc; }
    .gex-box.stop .label, .gex-box.stop .value { color: var(--red); }

    /* --- P&L / automation rows --- */
    .pnl-headline { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-bottom: 9px; }
    .pnl-row, .pos-row, .auto-row {
      display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 9px;
      border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; margin-bottom: 6px; font-size: 13px; flex-wrap: wrap;
    }
    .pnl-row .label, .pos-row .label, .auto-row .label { text-transform: none; }
    .panel-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }

    .sym { font-weight: 700; }
    .tiny { font-size: 11px; color: var(--muted); }
    .muted { color: var(--muted); }
    .good-text { color: var(--green); }
    .bad-text { color: var(--red); }
    .warn-text { color: var(--amber); }

    /* --- right (proposal) panel --- */
    /* Open Positions spans BOTH layout columns — a 9-column multi-account table needs full width. */
    .positions-fullwidth { grid-column: 1 / -1; min-width: 0; }
    .right-panel { min-width: 0; }
    .right-panel .panel-head { align-items: flex-start; }
    .right-panel button { padding: 4px 8px; font-size: 12px; min-height: 30px; }
    .proposal-toolbar { display: flex; gap: 8px; align-items: flex-start; justify-content: space-between; }
    .proposal-title h2 { margin: 0 0 3px; font-size: 13px; font-weight: 700; }
    .proposal-controls { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }

    .proposal-settings-bar {
      display: flex; flex-wrap: wrap; gap: 5px 10px; align-items: center;
      padding: 5px 12px; border-top: 1px solid var(--line);
    }
    .proposal-settings { display: inline-flex; gap: 6px; align-items: center; flex: 0 0 auto; flex-wrap: nowrap; min-width: max-content; }
    .setting-label { color: var(--muted); font-size: 12px; font-weight: 700; text-transform: uppercase; }
    .segmented {
      display: inline-grid; grid-auto-flow: column; grid-auto-columns: minmax(44px, auto);
      border: 1px solid var(--line); border-radius: 6px; overflow: hidden; background: white;
    }
    .segment-button {
      background: var(--panel); border: 0; border-right: 1px solid var(--line); border-radius: 0;
      box-shadow: none; color: var(--ink); cursor: pointer; min-height: 26px; padding: 3px 7px; font-weight: 600; font-size: 12px;
    }
    .segment-button:last-child { border-right: 0; }
    .segment-button.active { background: var(--green-bg); color: var(--green); font-weight: 700; }
    .segment-button:disabled { color: var(--muted); cursor: not-allowed; opacity: 0.7; }
    .checkbox-setting { display: inline-flex; align-items: center; gap: 4px; font-weight: 800; font-size: 12px; min-height: 32px; }
    .checkbox-setting input { min-width: 0; width: 16px; height: 16px; accent-color: var(--green); }
    .target-inputs { display: inline-flex; gap: 4px; align-items: center; }
    .target-inputs input {
      min-width: 0; width: 44px; height: 32px; font-weight: 800; text-align: center; padding: 4px;
      font-size: 12px; border: 1px solid var(--line); border-radius: 6px;
    }
    .moneyness-strip { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
    .moneyness-strip .badge { min-height: 22px; padding: 2px 7px; font-size: 11px; }

    .candidate-summary, .freshness { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 8px 0; }
    .freshness { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 7px 8px; background: #fbfcfe; min-width: 0; min-height: 54px; }
    .metric .value { margin-top: 2px; font-size: 16px; font-weight: 700; overflow-wrap: anywhere; }

    /* --- rich proposal card --- */
    .proposal-card {
      border: 2px solid #15803d; border-left-width: 7px; border-radius: 8px;
      padding: 8px 10px; margin-top: 9px; background: #f0fdf4; box-shadow: 0 1px 2px rgba(21, 128, 61, 0.12);
    }
    .proposal-card.sim { border-color: #f0d39a; border-left-color: var(--amber); background: #fffaf0; }
    .proposal-top { display: grid; grid-template-columns: 1fr auto; gap: 6px; align-items: start; }
    .proposal-side { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
    .trade-labels { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 5px; }
    .trade-number {
      display: inline-flex; align-items: center; min-height: 24px; border-radius: 6px;
      padding: 2px 8px; background: #14532d; color: #fff; font-size: 12px; font-weight: 800;
    }
    .proposal-card.sim .trade-number { background: var(--amber); }
    .trade-moneyness .badge { min-height: 24px; padding: 2px 8px; font-size: 12px; font-weight: 800; }
    .proposal-name { margin-top: 4px; font-weight: 700; overflow-wrap: anywhere; }
    .proposal-meta { margin-top: 2px; color: var(--muted); font-size: 12px; }
    /* score circle */
    .score-badge {
      width: 48px; height: 48px; border-radius: 50%;
      display: flex; flex-direction: column; align-items: center; justify-content: center; color: #fff;
    }
    .score-badge.high { background: #166534; }
    .score-badge.mid { background: #854f0b; }
    .score-badge.low { background: #6b7280; }
    .score-num { font-size: 19px; font-weight: 700; line-height: 1; }
    .score-cap { font-size: 9px; opacity: 0.85; }

    .proposal-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 6px; }
    .proposal-card .metric { padding: 4px 7px; min-height: 0; background: #ffffff; }
    .proposal-card .metric .value { margin-top: 1px; font-size: 13px; }
    .qty-control { display: inline-flex; gap: 6px; align-items: center; margin-top: 4px; flex-wrap: wrap; }
    .qty-control .segment-button { min-width: 34px; padding: 3px 7px; }
    .order-note { margin-top: 4px; color: var(--muted); line-height: 1.35; font-size: 12px; overflow-wrap: anywhere; }
    .legs { margin-top: 4px; display: grid; gap: 3px; font-family: Consolas, "Courier New", monospace; font-size: 12px; }
    .leg { background: #eef2f7; color: var(--ink); border-radius: 6px; padding: 5px 6px; overflow-wrap: anywhere; }
    .tos-head, .exit-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 5px; }
    .tos-actions, .exit-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; justify-content: flex-end; }
    .order-line {
      margin-top: 5px; background: #111827; color: #f9fafb; border-radius: 6px; padding: 8px 10px;
      overflow-x: auto; white-space: pre; font-family: Consolas, "Courier New", monospace; font-size: 13px; font-weight: 700;
    }
    .proposal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
    .reasons { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 6px; }
    .proposal-card .reasons .badge { min-height: 22px; padding: 2px 7px; font-size: 11px; }
    .note-list { margin-top: 4px; color: #7c2d12; font-size: 12px; font-weight: 700; line-height: 1.35; }
    .proposal-card.sim .note-list { color: #6f4200; }
    .exit-plan { border-top: 1px solid var(--line); margin-top: 5px; padding-top: 5px; }
    .exit-targets { display: grid; gap: 6px; margin-top: 6px; }
    .exit-target { font-weight: 700; font-size: 12px; color: var(--ink); overflow-wrap: anywhere; }
    .exit-order-line {
      display: block; margin-top: 5px; background: #e5e7eb; color: #111827; border-radius: 6px; padding: 6px 8px;
      overflow-x: auto; white-space: pre; font-family: Consolas, "Courier New", monospace; font-size: 12px; font-weight: 700;
    }
    .accounts { border: 1px solid var(--line); border-radius: 8px; margin-top: 8px; background: #fbfcfe; }
    .accounts-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 9px; border-bottom: 1px solid var(--line-soft); }
    .account-list { display: grid; gap: 6px; padding: 8px; }
    .account-row {
      display: grid; grid-template-columns: auto 1fr auto; gap: 8px; align-items: center;
      border: 1px solid var(--line); border-radius: 6px; padding: 4px 6px; background: white; font-size: 12px;
    }
    .account-row.balance-ok { background: #eefaf2; border-color: #b7dfc5; }
    .account-row.balance-low { background: #fff1f1; border-color: #f2bcbc; }
    .account-row.disabled { opacity: 0.62; background: #fff1f1; border-color: #f2bcbc; }
    .account-row input { min-width: 0; width: 16px; height: 16px; accent-color: var(--blue); }
    .send-status { margin-top: 6px; font-size: 12px; color: var(--muted); overflow-wrap: anywhere; min-height: 16px; }
    .empty { color: var(--muted); min-height: 60px; display: grid; place-items: center; text-align: center; padding: 18px; border: 1px dashed var(--line); border-radius: 8px; background: #fbfcfe; font-size: 12px; line-height: 1.4; }

    @media (max-width: 1100px) {
      .layout, .topbar, .kpis, .candidate-summary, .freshness, .proposal-stats { grid-template-columns: 1fr; }
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .proposal-toolbar { flex-direction: column; }
      .proposal-controls { justify-content: flex-start; }
      .top-actions { justify-content: flex-start; }
    }
    @media (max-width: 600px) {
      .page { padding: 12px; }
      .title h1 { font-size: 17px; }
      input { min-width: 0; width: 100%; }
      .kpis { grid-template-columns: 1fr; }
      .account-row { grid-template-columns: auto 1fr; }
      .account-row .badge { grid-column: 1 / -1; }
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="layout">
      <div class="dashboard-main">
        <header class="topbar">
          <div class="title">
            <h1>Schwab Market Scanner</h1>
            <div class="sub" id="last-update">Loading...</div>
          </div>
          <div class="top-actions">
            <button class="ghost" id="mute-button" title="Mute audio cues" onclick="toggleMute()">🔔 Mute</button>
            <button class="primary" id="build-all-button" data-run-scan-button onclick="runScan(true)">Build All</button>
          </div>
        </header>

        <div class="kpis" aria-label="Platform status">
          <div class="kpi"><div class="label">Live</div><div class="value" id="kpi-service">...</div></div>
          <div class="kpi"><div class="label">Orders Live</div><div class="value" id="kpi-mode">...</div></div>
          <div class="kpi"><div class="label">Planner</div><div class="value" id="kpi-regime">...</div></div>
          <div class="kpi"><div class="label">Schwab Ready</div><div class="value" id="kpi-schwab">...</div></div>
          <div class="kpi"><div class="label">Proposals</div><div class="value" id="kpi-proposals">...</div></div>
        </div>

        <section class="panel" id="platform-panel">
          <div class="panel-head">
            <div class="panel-title">Platform</div>
            <div class="badges">
              <span class="badge" id="ps-token-badge">token --</span>
              <span class="badge" id="ps-tier-badge">Tier --</span>
              <span class="badge" id="ps-win-badge">win --</span>
              <button class="danger" id="platform-kill-button" type="button" title="Kill all automation"
                      onclick="killSwitch()"
                      style="min-height:22px;padding:1px 9px;font-size:11px;background:#fee2e2;color:#991b1b;border-color:#fca5a5;font-weight:700;">KILL</button>
            </div>
          </div>
          <div class="platform-rows">
            <div class="platform-row platform-strip" id="platform-strip"></div>
            <div class="platform-row">
              <span class="label">Tier</span>
              <span class="segmented" id="automation-tier-buttons" role="group" aria-label="Automation tier">
                <button class="segment-button" type="button" onclick="setTier('off')">Off</button>
                <button class="segment-button" type="button" onclick="setTier('1')">1</button>
                <button class="segment-button" type="button" onclick="setTier('2')">2</button>
                <button class="segment-button" type="button" onclick="setTier('3')">3</button>
              </span>
              <span class="ps-mode" id="ps-mode" title="Tier label">manual send</span>
              <button class="ghost" type="button" onclick="releaseKill()" style="min-height:22px;padding:1px 9px;font-size:11px;">Release kill</button>
              <button class="ghost" type="button" onclick="loadAutomation()" style="min-height:22px;padding:1px 9px;font-size:11px;">Refresh</button>
            </div>
            <div class="platform-row">
              <span class="label">Enrich</span>
              <label class="flag-toggle"><input type="checkbox" checked disabled><span>scoring</span></label>
              <label class="flag-toggle"><input type="checkbox" checked disabled><span>GEX exits</span></label>
              <span class="ps-mode" title="Order-flow enrichment is N/A for the Scanner (gap-scan driven, futures excluded)">order flow N/A</span>
            </div>
            <div class="platform-row">
              <span class="label">P&amp;L</span>
              <span>Today <b id="ps-pnl-today" class="good-text">$0</b></span>
              <span>Wk <b id="ps-pnl-week" class="good-text">$0</b></span>
              <span>Mo <b id="ps-pnl-month" class="good-text">$0</b></span>
              <span>All <b id="ps-pnl-all" class="good-text">$0</b></span>
              <span class="muted" id="pnl-status">--</span>
              <button class="ghost" id="pnl-sync-button" type="button" onclick="syncPnl()" title="Pull recent Schwab transactions and record realized P&amp;L" style="min-height:20px;padding:1px 9px;font-size:11px;">Sync P&amp;L</button>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Operating State</div>
            <div class="badges" id="state-badges"></div>
          </div>
          <div class="state-summary" id="state-summary" title="">Loading scanner state...</div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Top Candidates <span class="tiny" style="font-weight:400;">gap-scan signals · this session</span></div>
            <div class="candidate-actions">
              <div class="muted" id="candidate-count">0 shown</div>
              <button class="ghost" id="refresh-prices-button" data-run-scan-button onclick="runScan(false)">Refresh Prices</button>
            </div>
          </div>
          <div class="table-wrap">
            <table class="signals-table">
              <thead>
                <tr>
                  <th style="width: 17%;">Symbol</th>
                  <th style="width: 14%;">Bias</th>
                  <th style="width: 13%;">Price</th>
                  <th style="width: 12%;">Gap</th>
                  <th style="width: 16%;">PM Vol</th>
                  <th style="width: 18%;">Build</th>
                  <th>Read</th>
                </tr>
              </thead>
              <tbody id="candidate-rows">
                <tr><td colspan="7" class="muted">Loading...</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Realized P&amp;L</div>
            <div class="panel-actions">
              <span class="muted" id="pnl-status-detail">--</span>
              <button class="ghost" id="pnl-sync-button-2" onclick="syncPnl()">Sync P&amp;L</button>
            </div>
          </div>
          <div class="panel-body" id="pnl-body">
            <div class="muted">Loading P&amp;L...</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Automation</div>
            <div class="panel-actions">
              <span class="muted" id="automation-status-label">--</span>
              <button class="ghost" onclick="loadAutomation()">Refresh</button>
            </div>
          </div>
          <div class="panel-body" id="automation-body">
            <div class="muted">Loading automation status...</div>
          </div>
        </section>
      </div>

      <aside class="dashboard-aside">
        <section class="panel right-panel">
          <div class="panel-head proposal-toolbar">
            <div class="proposal-title">
              <div class="panel-title" style="display:block;">Current Proposal</div>
              <div class="muted" id="proposal-subtitle">Select a candidate.</div>
            </div>
            <div class="proposal-controls">
              <span class="muted" id="proposal-status">ready</span>
              <button class="sound" onclick="soundReady()">Sound Ready</button>
              <button class="ghost" onclick="testSound()">Test Sound</button>
              <button class="ghost" onclick="showFirstProposal()">Show Proposal</button>
              <button class="ghost" id="preview-card-btn" onclick="previewProposalCard()" title="Show a sample simulated proposal card (clears on refresh)">preview card</button>
              <button class="ghost" disabled>Mark Reviewed</button>
            </div>
          </div>
          <div class="proposal-settings-bar" aria-label="Current proposal settings">
            <span class="proposal-settings" aria-label="Expiry settings">
              <span class="setting-label">Expiry</span>
              <span class="segmented" id="expiry-buttons" role="group" aria-label="Proposal expiry"></span>
            </span>
            <span class="proposal-settings" aria-label="Moneyness settings">
              <label class="checkbox-setting"><input id="allow-itm-checkbox" type="checkbox" onchange="setAllowItm(this.checked)">ITM</label>
              <label class="checkbox-setting" title="Auto-close an open position when the opposite signal fires (ships OFF)"><input id="close-reversal-checkbox" type="checkbox" onchange="setCloseOnReversal(this.checked)">Close on Reversal</label>
              <label class="checkbox-setting" title="OTOCO (1st Triggers OCO): place the entry as bracketed slices (e.g. 5/3/2) so the target+stop are attached at Schwab and activate on fill. Single-leg only."><input id="otoco-checkbox" type="checkbox" onchange="setOtoco(this.checked)">OTOCO Bracket</label>
            </span>
            <span class="proposal-settings" aria-label="Max loss settings">
              <span class="setting-label">Max Loss</span>
              <span class="segmented" id="max-loss-buttons" role="group" aria-label="Proposal max loss"></span>
            </span>
            <span class="proposal-settings" aria-label="Entry offset settings">
              <span class="setting-label">Entry +</span>
              <span class="segmented" id="entry-offset-buttons" role="group" aria-label="Proposal entry offset"></span>
            </span>
            <span class="proposal-settings" aria-label="Target settings">
              <span class="setting-label">Target %</span>
              <span class="target-inputs" id="target-inputs" role="group" aria-label="Proposal targets"></span>
              <button class="ghost" onclick="applyTargets()">Apply</button>
            </span>
          </div>
          <div class="panel-body">
            <div class="moneyness-strip">
              <span class="setting-label">Moneyness</span>
              <span class="badge green">ITM</span>
              <span class="badge">ATM</span>
              <span class="badge gray">OTM</span>
            </div>
            <div id="proposal-notice" class="notice">Loading scanner state...</div>
            <div class="freshness" id="quote-freshness"></div>
            <div class="candidate-summary">
              <div class="metric"><div class="label">Underlying</div><div class="value" id="metric-underlying">...</div></div>
              <div class="metric"><div class="label">Gap</div><div class="value" id="metric-gap">...</div></div>
              <div class="metric"><div class="label">PM High</div><div class="value" id="metric-pmh">...</div></div>
              <div class="metric"><div class="label">Prev High</div><div class="value" id="metric-prev-high">...</div></div>
            </div>
            <div id="proposal-cards"></div>
          </div>
        </section>
      </aside>

      <section class="panel positions-fullwidth">
        <div class="panel-head">
          <div class="panel-title">Open Positions <span class="muted tiny" id="positions-note">dashboard-tracked · saved across restarts</span></div>
          <div class="panel-actions">
            <span class="segmented" id="positions-mode" role="group" aria-label="Positions source">
              <button class="segment-button active" type="button" data-pos-mode="tracked" onclick="setPositionsMode('tracked')">Tracked</button>
              <button class="segment-button" type="button" data-pos-mode="all" onclick="setPositionsMode('all')">All</button>
            </span>
            <span class="muted" id="positions-status">--</span>
            <button class="ghost" id="positions-refresh-button" onclick="loadPositions(true)">Refresh</button>
          </div>
        </div>
        <div class="panel-body" id="positions-body">
          <div class="muted">Loading positions...</div>
        </div>
      </section>
    </section>
  </main>

<script>
const MAX_PROPOSAL_QUANTITY = 10;
let appState = {
  health: null,
  schwab: null,
  scan: null,
  selectedSymbol: null,
  currentProposals: [],
  quantities: {},
  selectedProposalIndex: 0,
  accounts: [],
  accountNotes: [],
  accountsLoading: false,
  accountsLoadedForKey: "",
  selectedAccountIds: new Set(),
  sendResponses: {},
  exitSendResponses: {},
  orderStatuses: {},
  soundArmed: false,
  pnl: null,
  positions: [],
  positionErrors: [],
  automation: null,
  muted: false,
  lastTopSymbol: null,
  settings: {
    settingsVersion: 4,
    expiry: "AUTO",
    expiryChoices: ["AUTO", "0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY"],
    allowItm: true,
    closeOnReversal: false,
    otoco: true,
    maxLoss: 300,
    maxLossChoices: [200, 300, 400, 500],
    entryOffsetCents: 10,
    entryOffsetChoices: [10, 20, 30, 40, 50],
    targets: [20, 50, 60]
  }
};

function byId(id) { return document.getElementById(id); }
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
}
function money(value) { return value === null || value === undefined || Number.isNaN(Number(value)) ? "--" : "$" + Number(value).toFixed(2); }
function plainMoney(value) { return value === null || value === undefined || Number.isNaN(Number(value)) ? "--" : Number(value).toFixed(2); }
function pct(value) { return value === null || value === undefined || Number.isNaN(Number(value)) ? "--" : Number(value).toFixed(2) + "%"; }
function intFmt(value) { return value === null || value === undefined ? "0" : Number(value).toLocaleString(); }
function shortTime(value) {
  if (!value) return "No scan";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}
function badge(text, tone) {
  return `<span class="badge ${tone || ""}">${esc(text)}</span>`;
}
function reasonBadges(items, tone) {
  return (items || []).map(item => badge(item, tone || "gray")).join("");
}
function candidateProposals(candidate) { return candidate?.proposals || []; }
function allProposals(scan) {
  return (scan?.top_candidates || []).flatMap(candidate => candidate.proposals || []);
}
function isSimProposal(proposal) {
  return String(proposal?.id || "").startsWith("sim_") || (proposal?.reasons || []).includes("SIM_ONLY");
}
function setStatus(text) { byId("last-update").textContent = text; }
function activeConfig() { return appState.health?.config || {}; }
function liveGateOpen() { return Boolean(activeConfig().live_gate_open); }

async function fetchJson(url, opts) {
  const res = await fetch(url, opts || {});
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { body: text }; }
  return { ok: res.ok, status: res.status, data };
}

// Injected from settings.service.api_key at render time. Empty string when no key is configured.
const SCANNER_API_KEY = __SCANNER_API_KEY__;

function authOptions(method, body) {
  const opts = { method, headers: {} };
  if (SCANNER_API_KEY) {
    opts.headers["X-API-Key"] = SCANNER_API_KEY;
  }
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  return opts;
}

function loadDashboardSettings() {
  try {
    const raw = localStorage.getItem("scannerDashboardSettings");
    if (!raw) return;
    const saved = JSON.parse(raw);
    appState.settings = { ...appState.settings, ...saved };
    if (!saved.settingsVersion && Array.isArray(saved.targets) && saved.targets.join(",") === "25,50,60") {
      appState.settings.targets = [20, 50, 60];
    }
    if (Number(saved.settingsVersion || 0) < 3) {
      appState.settings.expiry = "AUTO";
    }
    // v4: OTOCO bracketed entry is now ON by default; force-enable once for existing users
    // (their saved settings predate the flag or hold the old default OFF). Their toggle is
    // respected afterward since settingsVersion is bumped to 4.
    if (Number(saved.settingsVersion || 0) < 4) {
      appState.settings.otoco = true;
    }
    appState.settings.expiryChoices = ["AUTO", "0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY"];
    appState.settings.settingsVersion = 4;
  } catch {
    return;
  }
}
function saveDashboardSettings() {
  localStorage.setItem("scannerDashboardSettings", JSON.stringify(appState.settings));
}

function renderSetupControls() {
  const settings = appState.settings;
  byId("expiry-buttons").innerHTML = settings.expiryChoices.map(choice => {
    const label = choice === "AUTO" ? "Auto" : choice === "THIS_FRIDAY" ? "This Fri" : choice === "NEXT_WEEK_FRIDAY" ? "Next Fri" : choice;
    return `<button class="segment-button ${choice === settings.expiry ? "active" : ""}" type="button" onclick="setExpiry('${esc(choice)}')">${esc(label)}</button>`;
  }).join("");
  byId("allow-itm-checkbox").checked = Boolean(settings.allowItm);
  if (byId("close-reversal-checkbox")) byId("close-reversal-checkbox").checked = Boolean(settings.closeOnReversal);
  if (byId("otoco-checkbox")) byId("otoco-checkbox").checked = Boolean(settings.otoco);
  byId("max-loss-buttons").innerHTML = settings.maxLossChoices.map(choice => (
    `<button class="segment-button ${choice === settings.maxLoss ? "active" : ""}" type="button" onclick="setMaxLoss(${choice})">$${choice}</button>`
  )).join("");
  byId("entry-offset-buttons").innerHTML = settings.entryOffsetChoices.map(choice => (
    `<button class="segment-button ${choice === settings.entryOffsetCents ? "active" : ""}" type="button" onclick="setEntryOffset(${choice})">+${choice}c</button>`
  )).join("");
  byId("target-inputs").innerHTML = settings.targets.map((target, index) => (
    `<input id="target-${index}" inputmode="numeric" value="${esc(target)}" aria-label="Target ${index + 1} percent">`
  )).join("");
}

function forceAutoExpiry() {
  // Build / Build All / Refresh Prices always start from AUTO (Friday weeklies) so a proposal
  // reliably appears first. The user then picks a specific expiry to rebuild on that date.
  appState.settings.expiry = "AUTO";
  saveDashboardSettings();
}
function setExpiry(value) {
  appState.settings.expiry = value;
  saveDashboardSettings();
  // Changing the expiry after a proposal exists rebuilds the SELECTED candidate on that date
  // (the Build/Refresh buttons reset to AUTO; the dropdown is how you target a specific expiry).
  if (value !== "AUTO" && appState.scan && appState.selectedSymbol) {
    buildSelectedProposal(appState.selectedSymbol);
  } else {
    render();
  }
}
function setMaxLoss(value) {
  appState.settings.maxLoss = Number(value);
  saveDashboardSettings();
  render();
}
function setEntryOffset(value) {
  appState.settings.entryOffsetCents = Number(value);
  saveDashboardSettings();
  render();
}
function setCloseOnReversal(value) {
  appState.settings.closeOnReversal = Boolean(value);
  saveDashboardSettings();
  render();
}
function setOtoco(value) {
  appState.settings.otoco = Boolean(value);
  saveDashboardSettings();
  render();
}
function setAllowItm(value) {
  appState.settings.allowItm = Boolean(value);
  saveDashboardSettings();
  render();
}
function applyTargets() {
  const next = [0, 1, 2].map(index => Number(byId(`target-${index}`)?.value || 0)).filter(value => value > 0);
  appState.settings.targets = next.length ? next : [20, 50, 60];
  saveDashboardSettings();
  render();
}

function proposalSettingsParams(includeOptions) {
  const params = new URLSearchParams();
  if (includeOptions !== undefined) params.set("include_options", includeOptions ? "true" : "false");
  params.set("expiry_label", appState.settings.expiry || "NEXT_WEEK_FRIDAY");
  params.set("allow_itm", appState.settings.allowItm ? "true" : "false");
  params.set("max_loss", String(appState.settings.maxLoss || 300));
  params.set("entry_offset_cents", String(appState.settings.entryOffsetCents || 10));
  params.set("target_percentages", (appState.settings.targets || [20, 50, 60]).join(","));
  return params;
}

async function load() {
  loadDashboardSettings();
  loadMuteState();
  renderSetupControls();

  const [healthResult, schwabResult, scanResult] = await Promise.all([
    fetchJson("/health"),
    fetchJson("/schwab/status"),
    fetchJson("/scan/latest"),
  ]);
  appState.health = healthResult.data;
  appState.schwab = schwabResult.data;
  appState.scan = scanResult.data && scanResult.data.scan_id ? scanResult.data : null;
  render();
  await loadAccounts({ force: false });
  loadPnl();
  loadPositions(false);
  loadAutomation();
}

// ---- Realized P&L panel (#4) -------------------------------------------------
async function loadPnl() {
  const result = await fetchJson("/pnl/summary");
  if (result.ok) {
    appState.pnl = result.data;
    renderPnl();
  } else if (byId("pnl-status")) {
    byId("pnl-status").textContent = "load failed";
  }
}

async function syncPnl() {
  const button = byId("pnl-sync-button");
  const original = button ? button.textContent : "";
  if (button) { button.disabled = true; button.textContent = "Syncing..."; }
  if (byId("pnl-status")) byId("pnl-status").textContent = "syncing";
  try {
    const result = await fetchJson("/pnl/sync", authOptions("POST"));
    if (!result.ok) {
      if (byId("pnl-status")) byId("pnl-status").textContent = result.data?.detail || `HTTP ${result.status}`;
      return;
    }
    appState.pnl = result.data.summary || appState.pnl;
    if (byId("pnl-status")) byId("pnl-status").textContent = `+${Number(result.data.new_closes || 0)} closes`;
    if (byId("pnl-status-detail")) byId("pnl-status-detail").textContent = `+${Number(result.data.new_closes || 0)} closes`;
    renderPnl();
  } finally {
    if (button) { button.disabled = false; button.textContent = original || "Sync P&L"; }
  }
}

function moneySigned(value) {
  const num = Number(value);
  if (Number.isNaN(num)) return "--";
  return (num >= 0 ? "+$" : "-$") + Math.abs(num).toFixed(2);
}
function pnlClass(value) { return Number(value) >= 0 ? "good-text" : "bad-text"; }

function renderPnl() {
  const body = byId("pnl-body");
  if (!body) return;
  const data = appState.pnl;
  if (!data) { body.innerHTML = `<div class="muted">No P&amp;L yet.</div>`; return; }
  const pnl = data.pnl || {};
  const headline = `
    <div class="pnl-headline">
      <div class="metric"><div class="label">All Time</div><div class="value ${pnlClass(pnl.all_time)}">${moneySigned(pnl.all_time)}</div></div>
      <div class="metric"><div class="label">Today</div><div class="value ${pnlClass(pnl.today)}">${moneySigned(pnl.today)}</div></div>
      <div class="metric"><div class="label">Week</div><div class="value ${pnlClass(pnl.week)}">${moneySigned(pnl.week)}</div></div>
    </div>
    <div class="muted" style="margin-bottom:8px;">${Number(pnl.wins || 0)}W - ${Number(pnl.losses || 0)}L | ${Number(pnl.trade_count || 0)} trades | win rate ${pct(pnl.win_rate)}</div>`;
  const rows = (data.pnl_by_account || []).map(acct => `
    <div class="pnl-row">
      <span class="label"><strong>${esc(acct.account_label || acct.account_id)}</strong></span>
      <span>Today <span class="${pnlClass(acct.today)}">${moneySigned(acct.today)}</span> | Week <span class="${pnlClass(acct.week)}">${moneySigned(acct.week)}</span> | All <span class="${pnlClass(acct.all_time)}">${moneySigned(acct.all_time)}</span> | ${Number(acct.wins || 0)}W-${Number(acct.losses || 0)}L (${pct(acct.win_rate)})</span>
    </div>`).join("");
  body.innerHTML = headline + (rows || `<div class="muted">No per-account P&amp;L rows.</div>`);

  // Mirror the headline P&L into the grouped Platform panel strip (Today/Wk/Mo/All).
  const setPnlStrip = (id, value) => {
    const el = byId(id);
    if (!el) return;
    el.textContent = moneySigned(value);
    el.className = pnlClass(value);
  };
  setPnlStrip("ps-pnl-today", pnl.today);
  setPnlStrip("ps-pnl-week", pnl.week);
  setPnlStrip("ps-pnl-month", pnl.month != null ? pnl.month : pnl.week);
  setPnlStrip("ps-pnl-all", pnl.all_time);
  if (byId("ps-win-badge")) {
    byId("ps-win-badge").textContent = (pnl.win_rate == null || Number.isNaN(Number(pnl.win_rate))) ? "win --" : `win ${Number(pnl.win_rate).toFixed(0)}%`;
  }
}

// ---- Open Positions table (Unified-Platform style: ACCOUNT/SYMBOL/QTY/AVG/MARK/UNREALIZED) ----
function setPositionsMode(mode) {
  appState.positionsMode = mode;
  document.querySelectorAll("[data-pos-mode]").forEach(b => b.classList.toggle("active", b.dataset.posMode === mode));
  loadPositions(true);
}

async function loadPositions(manual) {
  const mode = appState.positionsMode || "tracked";
  if (manual && byId("positions-refresh-button")) {
    byId("positions-refresh-button").disabled = true;
    byId("positions-refresh-button").textContent = "Refreshing...";
  }
  if (byId("positions-status")) byId("positions-status").textContent = "loading";
  try {
    // Manual Refresh rebuilds the slow order#-based spread structure on the server (fresh=true).
    const freshParam = (manual && mode === "all") ? "&fresh=true" : "";
    const result = await fetchJson(`/positions?source=${encodeURIComponent(mode)}${freshParam}`);
    if (result.ok) {
      appState.positions = result.data.positions || [];
      appState.positionsNote = result.data.note || "";
      appState.positionErrors = result.data.errors || [];
      if (byId("positions-note")) byId("positions-note").textContent = mode === "all" ? "live from Schwab · all enabled accounts" : "dashboard-tracked · saved across restarts";
      if (byId("positions-status")) byId("positions-status").textContent = `${appState.positions.length} · ${shortTime(result.data.generated_at)}`;
      renderPositions();
    } else if (byId("positions-status")) {
      byId("positions-status").textContent = "load failed";
    }
  } finally {
    if (manual && byId("positions-refresh-button")) {
      byId("positions-refresh-button").disabled = false;
      byId("positions-refresh-button").textContent = "Refresh";
    }
  }
}

function formatExpiry(yymmdd) {
  if (!/^[0-9]{6}$/.test(yymmdd)) return yymmdd;
  return `${Number(yymmdd.slice(2, 4))}/${Number(yymmdd.slice(4, 6))}/${yymmdd.slice(0, 2)}`;
}
// "SOXS  260821C00010000" -> "SOXS 8/21/26 10 C"
function formatOptionLabel(sym) {
  const compact = String(sym || "").replace(/ /g, "");
  if (compact.length < 15) return sym || "";
  const under = compact.slice(0, compact.length - 15);
  const exp = compact.slice(-15, -9), right = compact.slice(-9, -8);
  const strike = parseInt(compact.slice(-8), 10) / 1000;
  const strikeStr = Number.isFinite(strike) ? String(strike) : compact.slice(-8);
  return `${under} ${formatExpiry(exp)} ${strikeStr} ${right}`;
}
// Group the two legs of a vertical (shared spread_id) into one net line per the order#-reconstruction.
function combineSpreadRows(positions) {
  const groups = {};
  const out = [];
  for (const p of positions) {
    if (p.spread_id) (groups[p.account_id + "|" + p.spread_id] ||= []).push(p);
    else out.push(p);
  }
  for (const key in groups) {
    const legs = groups[key];
    if (legs.length !== 2) { out.push(...legs); continue; }
    const long = legs.find(l => Number(l.qty) > 0) || legs[0];
    const short = legs.find(l => Number(l.qty) < 0) || legs[1];
    const netDebit = (long.avg != null && short.avg != null) ? (long.avg - short.avg) : null;
    const netMark = (long.mark != null && short.mark != null) ? (long.mark - short.mark) : null;
    out.push({
      account_id: long.account_id, account_label: long.account_label, underlying: long.underlying,
      _display: `${formatOptionLabel(long.symbol)} / ${formatOptionLabel(short.symbol)}`,
      qty: Math.abs(Number(long.qty)),
      avg: netDebit, mark: netMark,
      unrealized_pnl: legs.reduce((s, l) => s + (Number(l.unrealized_pnl) || 0), 0),
      target_price: long.target_price ?? short.target_price ?? null,
      stop_price: long.stop_price ?? short.stop_price ?? null,
      is_spread: true, closeable: false,
    });
  }
  return out;
}

const POSITION_COLUMNS = [
  ["account_label", "ACCOUNT", "text"],
  ["symbol", "SYMBOL", "text"],
  ["target_price", "TARGET", "num"],
  ["stop_price", "STOP", "num"],
  ["qty", "QTY", "num"],
  ["avg", "AVG", "num"],
  ["mark", "MARK", "num"],
  ["unrealized_pnl", "UNREALIZED", "num"],
];

function setPositionsSort(key) {
  if (appState.positionsSort === key) {
    appState.positionsSortDir = (appState.positionsSortDir === "asc") ? "desc" : "asc";
  } else {
    appState.positionsSort = key;
    appState.positionsSortDir = (key === "unrealized_pnl" || key === "qty" || key === "avg" || key === "mark") ? "desc" : "asc";
  }
  renderPositions();
}

function sortedPositions() {
  const positions = combineSpreadRows((appState.positions || []).slice());
  const key = appState.positionsSort || "unrealized_pnl";
  const dir = appState.positionsSortDir || "desc";
  const col = POSITION_COLUMNS.find(c => c[0] === key);
  const numeric = col && col[2] === "num";
  positions.sort((a, b) => {
    let av = a[key], bv = b[key];
    if (numeric) {
      if (av == null && bv == null) return 0;
      if (av == null) return 1;   // nulls last
      if (bv == null) return -1;
      return dir === "asc" ? av - bv : bv - av;
    }
    const cmp = String(av == null ? "" : av).localeCompare(String(bv == null ? "" : bv));
    return dir === "asc" ? cmp : -cmp;
  });
  return positions;
}

function renderPositions() {
  const body = byId("positions-body");
  if (!body) return;
  const positions = sortedPositions();
  const errs = (appState.positionErrors || []).map(e => `<div class="notice red" style="margin-top:6px;">${esc(e)}</div>`).join("");
  if (!positions.length) {
    const empty = (appState.positionsMode || "tracked") === "all" ? "No open option positions in the enabled accounts." : "No dashboard-tracked positions this session.";
    body.innerHTML = `<div class="empty">${empty}</div>${errs}`;
    return;
  }
  const sortKey = appState.positionsSort || "unrealized_pnl";
  const arrow = (appState.positionsSortDir || "desc") === "asc" ? " ▲" : " ▼";
  const head = POSITION_COLUMNS.map(([k, lbl, kind]) =>
    `<th class="${kind === "num" ? "num" : ""} sortable" onclick="setPositionsSort('${k}')">${lbl}${sortKey === k ? arrow : ""}</th>`
  ).join("") + "<th></th>";
  const rows = positions.map((pos) => {
    const sym = esc(pos.symbol).replace(/'/g, "\\'");
    const acct = esc(pos.account_id).replace(/'/g, "\\'");
    const isLong = Number(pos.qty) > 0;
    const qtyStr = (Number(pos.qty) > 0 ? "+" : "") + Number(pos.qty);
    const upnl = (pos.unrealized_pnl == null) ? "--" : `<span class="${pnlClass(pos.unrealized_pnl)}">${moneySigned(pos.unrealized_pnl)}</span>`;
    const statusId = `pos-status-${esc(pos.account_id)}-${esc(pos.symbol)}`;
    const action = (pos.is_spread || pos.is_spread_leg)
      ? `<span class="muted tiny">${pos.spread_aggregated ? "spread (agg)" : "spread"}</span>`
      : `<button class="danger small" onclick="closePosition('${sym}','${acct}',${Math.abs(Number(pos.qty)) || 1},${isLong},'${statusId}')">Close</button>`;
    const symLabel = pos._display || formatOptionLabel(pos.symbol);
    const tgtCell = pos.target_price == null ? "--" : Number(pos.target_price).toFixed(2);
    const stopCell = pos.stop_price == null ? "--" : `<span style="color:#c0392b">${Number(pos.stop_price).toFixed(2)}</span>`;
    return `<tr>
      <td>${esc(pos.account_label || pos.account_id)}</td>
      <td class="mono">${esc(symLabel)}</td>
      <td class="num">${tgtCell}</td>
      <td class="num">${stopCell}</td>
      <td class="num">${qtyStr}</td>
      <td class="num">${pos.avg == null ? "--" : Number(pos.avg).toFixed(2)}</td>
      <td class="num">${pos.mark == null ? "--" : Number(pos.mark).toFixed(2)}</td>
      <td class="num">${upnl}</td>
      <td class="pos-action">${action}<div class="send-status tiny" id="${statusId}"></div></td>
    </tr>`;
  }).join("");
  body.innerHTML = `<div class="table-wrap"><table class="pos-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>${errs}`;
}

async function closePosition(brokerSymbol, accountId, qty, isLong, statusId) {
  const status = statusId ? byId(statusId) : null;
  const ok = window.confirm(`Close ${qty} ${brokerSymbol} in ${accountId}? This cancels resting orders and sends a MARKET close order.`);
  if (!ok) { if (status) status.textContent = "cancelled"; return; }
  if (status) status.textContent = "sending...";
  const body = { account_id: accountId, broker_symbol: brokerSymbol, qty: qty, is_long: isLong, confirm_live_order: true };
  const result = await fetchJson("/positions/close", authOptions("POST", body));
  if (!result.ok) {
    if (status) status.textContent = result.data?.detail || result.data?.body || `HTTP ${result.status}`;
    return;
  }
  const data = result.data || {};
  const r = (data.account_results || [])[0] || {};
  const reasons = (r.reasons || []).length ? " (" + r.reasons.join(", ") + ")" : "";
  if (status) status.textContent = `${data.status || "done"}${r.broker_order_id ? " " + r.broker_order_id : ""}${reasons}`;
  loadPositions(false);
}

// ---- Automation tiers (#7) --------------------------------------------------
async function loadAutomation() {
  const result = await fetchJson("/automation/status");
  if (result.ok) {
    appState.automation = result.data;
    renderAutomation();
  } else if (byId("automation-status-label")) {
    byId("automation-status-label").textContent = "load failed";
  }
}

async function postAutomation(url, body, labelEl) {
  const result = await fetchJson(url, authOptions("POST", body));
  if (!result.ok) {
    if (labelEl) labelEl.textContent = result.data?.detail || `HTTP ${result.status}`;
    return;
  }
  appState.automation = result.data;
  renderAutomation();
}

function setTier(tier) {
  const confirmNeeded = tier === "2" || tier === "3";
  postAutomation("/automation/tier", { tier, confirm: true }, byId("automation-status-label"));
}
function killSwitch() {
  postAutomation("/automation/kill", { reason: "dashboard" }, byId("automation-status-label"));
}
function releaseKill() {
  postAutomation("/automation/kill/release", undefined, byId("automation-status-label"));
}

function renderAutomation() {
  const body = byId("automation-body");
  if (!body) return;
  const data = appState.automation;
  if (!data) { body.innerHTML = `<div class="muted">No automation status.</div>`; return; }
  if (byId("automation-status-label")) byId("automation-status-label").textContent = data.tier_label || data.tier || "--";
  const kill = data.kill_switch || {};

  // Sync the grouped Platform panel's tier badge / mode label / tier buttons (DOM-only).
  if (byId("ps-tier-badge")) byId("ps-tier-badge").textContent = data.tier_label || (data.tier != null ? `Tier ${data.tier}` : "Tier --");
  if (byId("ps-mode")) byId("ps-mode").textContent = kill.engaged ? "kill engaged" : (String(data.tier) === "off" ? "manual send" : (data.tier_label || "auto"));
  const platformTierWrap = byId("automation-tier-buttons");
  if (platformTierWrap) {
    Array.from(platformTierWrap.querySelectorAll(".segment-button")).forEach(btn => {
      const label = btn.textContent.trim().toLowerCase();
      const val = label === "off" ? "off" : label;
      btn.classList.toggle("active", String(data.tier) === val);
    });
  }

  const tierBtns = [["off", "Off"], ["1", "Tier 1"], ["2", "Tier 2"], ["3", "Tier 3"]].map(([value, label]) =>
    `<button class="segment-button ${String(data.tier) === value ? "active" : ""}" type="button" onclick="setTier('${value}')">${label}</button>`
  ).join("");
  body.innerHTML = `
    <div class="auto-row">
      <span class="label"><strong>${esc(data.tier_label || data.tier || "--")}</strong></span>
      <span>${badge(data.live_gate_open ? "LIVE GATE ON" : "LIVE GATE OFF", data.live_gate_open ? "red" : "green")}
        ${kill.engaged ? badge("KILL ENGAGED" + (kill.reason ? " (" + esc(kill.reason) + ")" : ""), "red") : badge("KILL OFF", "gray")}</span>
    </div>
    <div class="auto-row">
      <span class="label">Set Tier</span>
      <span class="segmented">${tierBtns}</span>
    </div>
    <div class="auto-row">
      <span class="label">Kill Switch</span>
      <span class="panel-actions">
        <button class="danger" onclick="killSwitch()">KILL</button>
        <button class="ghost" onclick="releaseKill()">Release kill</button>
      </span>
    </div>`;
}

// ---- Dashboard polish (#6): mute + audio cue --------------------------------
function loadMuteState() {
  try { appState.muted = localStorage.getItem("scanner_sound_muted") === "true"; } catch { appState.muted = false; }
  renderMuteButton();
}
function renderMuteButton() {
  const button = byId("mute-button");
  if (!button) return;
  button.textContent = appState.muted ? "🔕 Muted" : "🔔 Mute";
}
function toggleMute() {
  appState.muted = !appState.muted;
  try { localStorage.setItem("scanner_sound_muted", appState.muted ? "true" : "false"); } catch {}
  renderMuteButton();
}

function announceCandidate(direction) {
  if (appState.muted) return;
  try {
    if (window.speechSynthesis && (direction === "long" || direction === "short")) {
      const utter = new SpeechSynthesisUtterance(direction === "long" ? "Long" : "Short");
      window.speechSynthesis.speak(utter);
    }
  } catch {}
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const context = new AudioCtx();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.12, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.22);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.25);
  } catch {}
}

function maybeAnnounceTopCandidate() {
  const top = (appState.scan?.top_candidates || [])[0];
  const symbol = top?.symbol || null;
  if (symbol && symbol !== appState.lastTopSymbol) {
    if (appState.lastTopSymbol !== null) announceCandidate(top.direction);
    appState.lastTopSymbol = symbol;
  }
}

async function runScan(includeOptions = true) {
  forceAutoExpiry();  // Build All / Refresh Prices always run on AUTO so proposals appear.
  const opts = authOptions("POST");
  if (!opts) return;
  const buttons = Array.from(document.querySelectorAll("[data-run-scan-button]"));
  buttons.forEach(button => {
    button.dataset.originalText = button.dataset.originalText || button.textContent;
    button.disabled = true;
    button.textContent = button.id === "refresh-prices-button" ? "Refreshing..." : "Scanning...";
  });
  setStatus(includeOptions ? "Running full scan..." : "Refreshing prices...");
  byId("proposal-status").textContent = includeOptions ? "scanning" : "refreshing prices";
  byId("proposal-notice").className = "notice";
  byId("proposal-notice").textContent = includeOptions
    ? "Fetching fresh Schwab quotes, candles, and option chains..."
    : "Fetching fresh Schwab stock quotes and candles...";
  try {
    const result = await fetchJson(`/scan/run?${proposalSettingsParams(includeOptions).toString()}`, opts);
    renderProtectedResult(result);
  } finally {
    buttons.forEach(button => {
      button.disabled = false;
      button.textContent = button.dataset.originalText || "Run Scan";
    });
  }
}

async function buildSelectedProposal(symbolOverride) {
  const symbol = symbolOverride || appState.selectedSymbol;
  if (!symbol) {
    byId("proposal-status").textContent = "select a symbol";
    byId("proposal-notice").className = "notice";
    byId("proposal-notice").textContent = "Select a candidate on the left before building proposals.";
    return;
  }
  appState.selectedSymbol = symbol;
  appState.selectedProposalIndex = 0;
  render();
  const opts = authOptions("POST");
  if (!opts) return;
  const buttons = Array.from(document.querySelectorAll("[data-build-candidate-button]"));
  buttons.forEach(button => {
    button.dataset.originalText = button.dataset.originalText || button.textContent;
    button.disabled = true;
    if (button.dataset.symbol === symbol) button.textContent = `Building ${symbol}...`;
  });
  setStatus(`Building ${symbol} proposals...`);
  byId("proposal-status").textContent = `building ${symbol}`;
  byId("proposal-notice").className = "notice";
  byId("proposal-notice").textContent = `Fetching ${appState.settings.expiry} Schwab option chains only for ${symbol}.`;
  try {
    const result = await fetchJson(`/scan/selected/${encodeURIComponent(symbol)}?${proposalSettingsParams().toString()}`, opts);
    renderProtectedResult(result);
  } finally {
    buttons.forEach(button => {
      button.disabled = false;
      button.textContent = button.dataset.originalText || button.textContent;
    });
  }
}

function buildCandidate(event, symbol) {
  if (event) event.stopPropagation();
  forceAutoExpiry();
  buildSelectedProposal(symbol);
}

function renderProtectedResult(result) {
  if (!result.ok) {
    const detail = result.data?.detail || result.data?.message || result.data?.body || `HTTP ${result.status}`;
    byId("proposal-notice").textContent = `Request failed: ${detail}`;
    byId("proposal-status").textContent = "request failed";
    setStatus("Request failed");
    return;
  }
  appState.scan = result.data;
  render();
  // Whenever a build produces proposals, auto-refresh account balances so Accounts-to-Send is
  // current without an extra "Refresh Accounts" click. (Refresh Prices builds no proposals -> skip.)
  const hasProposals = (result.data?.candidates || []).some(c => (c.proposals || []).length);
  if (hasProposals) loadAccounts({ force: true });
}

function render() {
  renderSetupControls();
  const health = appState.health || {};
  const config = health.config || {};
  const schwab = appState.schwab || {};
  const scan = appState.scan;
  const proposals = allProposals(scan);

  // KPI badge row mirrors the Platform's LIVE / ORDERS LIVE / PLANNER / SCHWAB READY strip.
  byId("kpi-service").textContent = (health.status || "...").toUpperCase();
  byId("kpi-mode").textContent = config.live_gate_open ? "LIVE" : "BLOCKED";
  byId("kpi-regime").textContent = scan?.regime?.bias ? `PLANNER · ${scan.regime.bias}` : "PLANNER";
  byId("kpi-schwab").textContent = schwab.read_only_ready ? "READY" : (schwab.status || "...");
  byId("kpi-proposals").textContent = String(proposals.length);

  const hasSim = proposals.some(isSimProposal);

  // Grouped Platform panel badges (token / tier / win-rate) — DOM-only, derived from
  // the same state the strip uses; no new requests.
  const tokenOk = Boolean(schwab.read_only_ready);
  if (byId("ps-token-badge")) {
    byId("ps-token-badge").textContent = tokenOk ? "token valid" : "token check";
    byId("ps-token-badge").className = "badge " + (tokenOk ? "green" : "amber");
  }
  if (byId("ps-tier-badge")) {
    const tierLbl = appState.automation?.tier_label || (appState.automation?.tier != null ? `Tier ${appState.automation.tier}` : "Tier --");
    byId("ps-tier-badge").textContent = tierLbl;
  }
  if (byId("ps-win-badge")) {
    const wr = appState.pnl?.pnl?.win_rate;
    byId("ps-win-badge").textContent = (wr == null || Number.isNaN(Number(wr))) ? "win --" : `win ${Number(wr).toFixed(0)}%`;
  }
  byId("state-badges").innerHTML = [
    badge((config.execution_mode || "dry_run").toUpperCase(), config.execution_mode === "live" ? "red" : "gray"),
    badge(config.live_gate_open ? "LIVE GATE ON" : "LIVE GATE OFF", config.live_gate_open ? "red" : "green"),
    badge(schwab.read_only_ready ? "SCHWAB DATA READY" : "SCHWAB DATA WAITING", schwab.read_only_ready ? "green" : "amber"),
    hasSim ? badge("SIM PROPOSALS", "amber") : badge("CURRENT PROPOSALS", "green"),
    badge(appState.settings.allowItm ? "ITM ALLOWED" : "ATM/OTM ONLY", appState.settings.allowItm ? "green" : "gray"),
  ].join("");

  const ps = byId("platform-strip");
  if (ps) {
    const tokenOk = Boolean(schwab.read_only_ready);
    const ordersLive = Boolean(config.live_gate_open);
    const kill = Boolean(appState.automation?.kill_switch?.engaged);
    ps.innerHTML = [
      `TOKEN <strong class="${tokenOk ? "good-text" : "bad-text"}">${tokenOk ? "valid" : "check"}</strong>`,
      `ORDERS <strong class="${ordersLive ? "bad-text" : "good-text"}">${ordersLive ? "live" : "blocked"}</strong>`,
      `QUOTES <strong class="${tokenOk ? "good-text" : "warn-text"}">${tokenOk ? "ready" : "waiting"}</strong>`,
      `KILL <strong class="${kill ? "bad-text" : "muted"}">${kill ? "ON" : "off"}</strong>`,
    ].join(' <span class="muted">·</span> ');
  }

  const universe = scan?.universe || config.symbols || [];
  const stateSummary = [
    scan?.scan_id || "No scan",
    `${universe.length} symbols`,
    scan?.session || "...",
    config.live_gate_open ? "Live Enabled" : "Protected",
  ].join(" | ");
  byId("state-summary").textContent = stateSummary;
  byId("state-summary").title = universe.join(", ");
  byId("candidate-count").textContent = `${(scan?.top_candidates || []).length} shown`;
  setStatus(`Last update: ${shortTime(scan?.scanned_at || health.latest_scan_at)}`);
  renderBuildButton();
  renderMuteButton();
  maybeAnnounceTopCandidate();

  if (!scan) {
    byId("candidate-rows").innerHTML = `<tr><td colspan="7" class="muted">No scan has been saved yet.</td></tr>`;
    renderProposal(null);
    return;
  }

  const candidates = scan.top_candidates || [];
  if (!appState.selectedSymbol || !candidates.some(item => item.symbol === appState.selectedSymbol)) {
    const firstWithProposal = candidates.find(item => candidateProposals(item).length > 0);
    appState.selectedSymbol = (firstWithProposal || candidates[0] || {}).symbol || null;
  }
  renderBuildButton();
  byId("candidate-rows").innerHTML = candidates.map(candidateRow).join("") ||
    `<tr><td colspan="7" class="muted">No candidates.</td></tr>`;
  renderProposal(candidates.find(item => item.symbol === appState.selectedSymbol) || candidates[0]);
}

function renderBuildButton() {
  const buildButton = byId("build-all-button");
  if (!buildButton) return;
  buildButton.textContent = "Build All";
  buildButton.dataset.originalText = buildButton.textContent;
}

// Score breakdown (#5): candidate JSON carries metrics.gap_pct, metrics.premarket_volume,
// candidate.direction; regime bias lives on the scan. Render a small line under the score.
// Preview card (#3): inject a sample SIMULATED proposal so the operator can see a fully-populated
// proposal card (OCO target/stop, legs, TOS lines) without a live build. Marked sim -> not sendable.
// Mirrors the Unified Platform's "preview card". Clears on Refresh/Build or via "exit preview".
function _samplePreviewProposal() {
  const now = new Date().toISOString();
  return {
    id: "sim_preview", signal_id: "PREVIEW", symbol: "QQQ", direction: "long", structure: "single",
    status: "proposed", created_at: now, expiry: "2026-06-26", quantity: 1, underlying_price: 540.25,
    legs: [{ action: "BUY", qty: 1, symbol: "QQQ", broker_symbol: "QQQ   260626C00540000",
             expiry: "2026-06-26", strike: 540, right: "CALL", price: 4.20, bid: 4.10, ask: 4.20,
             mark: 4.15, delta: 0.52, open_interest: 4210, volume: 18234 }],
    debit: 420, max_loss: 420, natural_limit_price: 4.20, natural_debit: 420, send_limit_price: 4.30,
    width: null, net_delta: 0.52, score: 82,
    tos_order_line: "BUY +1 SINGLE QQQ 100 26 JUN 26 540 CALL @4.30 LMT",
    exit_targets: [{ target_index: 0, qty: 1, target_percent: 40, entry_fill_price: 4.30,
                     target_limit_price: 6.02, stop_loss_percent: 50, stop_trigger_price: 2.15,
                     estimated_profit: 172,
                     tos_exit_order_line: "SELL -1 SINGLE QQQ 100 26 JUN 26 540 CALL @6.02 LMT GTC",
                     tos_stop_order_line: "SELL -1 SINGLE QQQ 100 26 JUN 26 540 CALL @2.15 STP GTC" }],
    reasons: ["SIM_ONLY", "single_long_option", "atm_primary"],
    notes: ["PREVIEW sample — not a live proposal", "OCO exit: target 40% / stop 50%"],
    dry_run: true,
  };
}

function previewProposalCard() {
  const btn = byId("preview-card-btn");
  if (appState._previewActive) {  // toggle off -> restore the real view
    appState._previewActive = false;
    if (btn) btn.textContent = "preview card";
    render();
    return;
  }
  appState._previewActive = true;
  const sample = _samplePreviewProposal();
  appState.currentProposals = [sample];
  byId("proposal-subtitle").textContent = "PREVIEW — sample simulated proposal (QQQ)";
  byId("proposal-status").textContent = "preview";
  byId("proposal-notice").className = "notice";
  byId("proposal-notice").textContent = "PREVIEW: sample simulated proposal (not live). Click 'exit preview' or Refresh to restore.";
  try { byId("proposal-cards").innerHTML = proposalCard(sample, 0); } catch (e) { byId("proposal-cards").innerHTML = '<div class="empty">Preview render error.</div>'; }
  setMetrics({ current_price: 540.25, gap_pct: 2.1, premarket_high: 541.0, previous_high: 538.5 });
  if (btn) btn.textContent = "exit preview";
}

// Build a notice that names the SPECIFIC block reason(s), not just the generic catch-all.
// "no_proposals_after_filters" is always appended by the planner, so we surface what's
// behind it: e.g. "no contracts for this expiry (try AUTO)" vs "filtered: low OI, wide spread".
function blockedNoticeText(reasons) {
  const list = (reasons || []).filter(Boolean);
  const specifics = list.filter((r) => r !== "no_proposals_after_filters");
  if (!specifics.length) return "No eligible proposal survived the current option-chain filters.";
  const noContracts = specifics.some((r) => String(r).indexOf("_contracts_for_expiry") !== -1);
  if (noContracts) {
    return "No option contracts exist for the selected expiry — these tickers have no expiry that day. Switch Expiry to AUTO (Friday weeklies) and rebuild.";
  }
  const labels = Array.from(new Set(specifics.map((r) => blockedReasonSummary([r]))));
  return `Filtered out: ${labels.join(", ")}. (${specifics.length} contract-filter reasons — hover a candidate's chip or see below for detail.)`;
}

// Turn the planner's raw block reasons into one short, human label for the chip.
// The full list is shown on hover (title) and in the proposal detail panel.
function blockedReasonSummary(reasons) {
  const list = (reasons || []).filter(Boolean);
  if (!list.length) return "no proposals";
  // Prefer the most specific reason over the generic catch-all.
  const specific = list.find((r) => r !== "no_proposals_after_filters") || list[0];
  const key = String(specific).split(":")[0];
  const friendly = {
    debit_out_of_range: "cost out of range",
    spread_debit_out_of_range: "spread cost out of range",
    no_spread_leg: "no spread leg",
    no_eligible_long_contracts: "no eligible contracts",
    no_proposals_after_filters: "filtered out",
    options_planner_disabled: "planner disabled",
    signal_decision_blocked: "signal blocked",
    no_valid_target_expiries: "no expiry",
    wide_bid_ask_spread: "wide spread",
    low_open_interest: "low OI",
    stale_quote: "stale quote",
    delta_out_of_range: "delta out of range",
    invalid_bid_ask: "no quote",
  };
  for (const prefix of Object.keys(friendly)) {
    if (key.startsWith(prefix) || String(specific).indexOf(prefix) !== -1) return friendly[prefix];
  }
  return key.replace(/_/g, " ");
}

function candidateRow(candidate) {
  const metrics = candidate.metrics || {};
  const selected = candidate.symbol === appState.selectedSymbol ? " selected" : "";
  const proposals = candidateProposals(candidate);
  const blockedReasons = candidate.proposal_blocked_reasons || [];
  const tone = candidate.action === "CALL_BIAS" ? "green" : candidate.action === "PUT_BIAS" ? "amber" : "gray";
  const selectedAttr = esc(candidate.symbol).replace(/'/g, "\\'");
  const buildLabel = proposals.length ? `Rebuild ${candidate.symbol}` : `Build ${candidate.symbol}`;
  const buildBadge = proposals.length
    ? badge(`${proposals.length} ready`, "green")
    : blockedReasons.length
      ? `<span class="badge amber" title="${esc(blockedReasons.join(" | "))}">blocked: ${esc(blockedReasonSummary(blockedReasons))}</span>`
      : "";
  return `<tr class="candidate-row${selected}" onclick="selectCandidate('${selectedAttr}')">
    <td><div class="sym">${esc(candidate.symbol)}</div><div class="tiny">rank ${candidate.rank || ""}</div></td>
    <td>${badge(candidate.action || "WATCH", tone)}</td>
    <td>${plainMoney(metrics.current_price)}</td>
    <td class="${Number(metrics.gap_pct || 0) >= 0 ? "good-text" : "bad-text"}">${pct(metrics.gap_pct)}</td>
    <td>${intFmt(metrics.premarket_volume)}</td>
    <td><div class="build-cell"><button class="ghost row-build" data-build-candidate-button data-symbol="${esc(candidate.symbol)}" onclick="buildCandidate(event, '${selectedAttr}')">${esc(buildLabel)}</button>${buildBadge}</div></td>
    <td><div>${esc((candidate.reasons || []).join(", ") || "--")}</div><div class="tiny">${esc((candidate.warnings || []).join(", "))}</div></td>
  </tr>`;
}

function selectCandidate(symbol) {
  appState.selectedSymbol = symbol;
  appState.selectedProposalIndex = 0;
  render();
}

function renderProposal(candidate) {
  if (!candidate) {
    byId("proposal-subtitle").textContent = "No candidate selected.";
    byId("proposal-status").textContent = "no proposal";
    byId("proposal-notice").className = "notice";
    byId("proposal-notice").textContent = "Refresh prices, select a candidate, then build selected proposals.";
    byId("proposal-cards").innerHTML = `<div class="empty">No proposal selected.</div>`;
    renderQuoteFreshness([]);
    setMetrics(null);
    return;
  }
  const metrics = candidate.metrics || {};
  const proposals = candidateProposals(candidate);
  const blockedReasons = candidate.proposal_blocked_reasons || [];
  appState.currentProposals = proposals;
  const sim = proposals.some(isSimProposal);
  const moneyness = proposals.map(proposalMoneyness).filter(Boolean);
  const uniqueMoneyness = Array.from(new Set(moneyness)).join(", ") || "ATM/OTM";
  byId("proposal-subtitle").textContent = `${candidate.symbol} ${candidate.action} | ${proposals.length} proposal${proposals.length === 1 ? "" : "s"} | ${uniqueMoneyness}`;
  byId("proposal-status").textContent = proposals.length ? "ready" : blockedReasons.length ? "blocked" : "not built";
  byId("proposal-notice").className = proposals.length && !sim ? "notice green" : "notice";
  byId("proposal-notice").textContent = proposals.length
    ? sim
      ? "SIM ONLY: replayed Friday underlying prices with current Schwab option-chain contract data. Order sending is blocked."
      : "Access token is present for read-only market-data calls. Schwab order placement remains controlled by scanner execution gates."
    : blockedReasons.length
      ? blockedNoticeText(blockedReasons)
      : `Click Build ${candidate.symbol} to fetch option proposals for only this ticker.`;
  setMetrics(metrics);
  renderQuoteFreshness(proposals);
  byId("proposal-cards").innerHTML = proposals.length
    ? proposals.map((proposal, index) => proposalCard(proposal, index)).join("")
    : `<div class="empty">${esc((blockedReasons.length ? blockedReasons : [`Build ${candidate.symbol} to fetch selected proposals.`]).join(" | "))}</div>`;
}

function setMetrics(metrics) {
  byId("metric-underlying").textContent = plainMoney(metrics?.current_price);
  byId("metric-gap").textContent = pct(metrics?.gap_pct);
  byId("metric-pmh").textContent = plainMoney(metrics?.premarket_high);
  byId("metric-prev-high").textContent = plainMoney(metrics?.previous_high);
}

function renderQuoteFreshness(proposals) {
  const proposalList = proposals || [];
  const times = proposalList.flatMap(proposalQuoteTimes).filter(date => date && !Number.isNaN(date.getTime()));
  const now = new Date();
  const freshest = times.length ? new Date(Math.max(...times.map(date => date.getTime()))) : null;
  const ageSeconds = freshest ? Math.max(0, Math.round((now.getTime() - freshest.getTime()) / 1000)) : null;
  const hasSim = proposalList.some(isSimProposal);
  const staleCount = freshest && ageSeconds > 300 ? proposalList.length : 0;
  const status = !proposalList.length ? "NOT CHECKED" : hasSim ? "SIM CURRENT CHAIN" : staleCount ? "STALE" : "FRESH";
  const tone = status === "FRESH" ? "green" : status === "STALE" ? "red" : "amber";
  byId("quote-freshness").innerHTML = `
    <div class="metric"><div class="label">Quote Freshness</div><div class="value">${badge(status, tone)}</div></div>
    <div class="metric"><div class="label">Freshest Quote</div><div class="value">${freshest ? esc(freshest.toLocaleString()) : "--"}</div></div>
    <div class="metric"><div class="label">Quote Age</div><div class="value">${ageSeconds === null ? "--" : formatAge(ageSeconds)} / ${staleCount} of ${proposalList.length} stale</div></div>`;
}

function proposalQuoteTimes(proposal) {
  const times = [];
  (proposal.legs || []).forEach(leg => {
    ["timestamp", "quote_time", "last_quote_time"].forEach(key => {
      if (leg[key]) times.push(new Date(leg[key]));
    });
  });
  (proposal.notes || []).forEach(note => {
    const match = String(note).match(/timestamp:\\s*([^\\s]+)/i);
    if (match) times.push(new Date(match[1]));
  });
  if (!times.length && proposal.created_at) times.push(new Date(proposal.created_at));
  return times;
}

function formatAge(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function primaryLeg(proposal) {
  return (proposal.legs || []).find(leg => leg.action === "BUY") || (proposal.legs || [])[0] || {};
}

function proposalMoneyness(proposal) {
  const leg = primaryLeg(proposal);
  const underlying = Number(proposal?.underlying_price);
  const strike = Number(leg?.strike);
  const right = String(leg?.right || "").toUpperCase();
  if (!underlying || !strike || !right) return "ATM/OTM";
  const tolerance = Math.max(0.5, Math.abs(underlying) * 0.0035);
  if (Math.abs(underlying - strike) <= tolerance) return "ATM";
  const itm = right === "CALL" ? underlying > strike : underlying < strike;
  return itm ? "ITM" : "OTM";
}

function moneynessTone(value) {
  if (value === "ITM") return "green";
  if (value === "OTM") return "gray";
  return "";
}

function proposalUnitLimit(proposal) {
  const natural = Number(proposal?.natural_limit_price || 0);
  const selectedOffset = Number(appState.settings.entryOffsetCents || 0) / 100;
  if (natural > 0) return roundMoney(natural + selectedOffset);
  const sendLimit = Number(proposal?.send_limit_price || 0);
  if (sendLimit > 0) return sendLimit;
  const quantity = Number(proposal?.quantity || 0);
  const debit = Number(proposal?.debit || 0);
  if (quantity > 0 && debit > 0) return roundMoney(debit / (quantity * 100));
  return Number(primaryLeg(proposal).ask || primaryLeg(proposal).price || 0);
}

function selectedProposalQuantity(proposal) {
  const saved = Number(appState.quantities[proposal.id] || proposal.quantity || 1);
  return Math.max(1, Math.min(MAX_PROPOSAL_QUANTITY, saved));
}

function roundMoney(value) {
  return Math.round(Number(value || 0) * 100) / 100;
}

function formatTosStrike(strike) {
  const value = Number(strike || 0);
  return Number.isInteger(value) ? String(value) : String(strike);
}

function formatTosExpiry(expiry) {
  const parts = String(expiry || "").split("-").map(part => Number(part));
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  if (parts.length !== 3 || parts.some(part => Number.isNaN(part))) return String(expiry || "");
  return `${String(parts[2]).padStart(2, "0")} ${months[Math.max(0, Math.min(11, parts[1] - 1))]} ${String(parts[0]).slice(-2)}`;
}

function tosOrderLine(proposal, quantity, limitPrice) {
  const legs = proposal.legs || [];
  if (!legs.length) return proposal.tos_order_line || "";
  const structure = proposal.structure === "debit_vertical" ? "VERTICAL" : "SINGLE";
  const strikes = legs.map(leg => formatTosStrike(leg.strike)).join("/");
  const right = legs[0]?.right || "CALL";
  const prefix = isSimProposal(proposal) ? "SIM ONLY " : "";
  return `${prefix}BUY +${quantity} ${structure} ${String(proposal.symbol || "").toUpperCase()} 100 ${formatTosExpiry(proposal.expiry)} ${strikes} ${right} @${Number(limitPrice || 0).toFixed(2)} LMT`;
}

function tosExitOrderLine(proposal, quantity, limitPrice) {
  const legs = proposal.legs || [];
  if (!legs.length) return "";
  const structure = proposal.structure === "debit_vertical" ? "VERTICAL" : "SINGLE";
  const strikes = legs.map(leg => formatTosStrike(leg.strike)).join("/");
  const right = legs[0]?.right || "CALL";
  return `SELL -${quantity} ${structure} ${String(proposal.symbol || "").toUpperCase()} 100 ${formatTosExpiry(proposal.expiry)} ${strikes} ${right} @${Number(limitPrice || 0).toFixed(2)} LMT GTC`;
}

function adjustedProposalForQuantity(rawProposal) {
  const quantity = selectedProposalQuantity(rawProposal);
  const unitLimit = proposalUnitLimit(rawProposal);
  const natural = Number(rawProposal.natural_limit_price || unitLimit || 0);
  const debit = roundMoney(unitLimit * 100 * quantity);
  const naturalDebit = roundMoney(natural * 100 * quantity);
  const legs = (rawProposal.legs || []).map(leg => ({ ...leg, qty: quantity }));
  return {
    ...rawProposal,
    quantity,
    legs,
    debit,
    max_loss: debit,
    natural_debit: naturalDebit,
    send_limit_price: unitLimit,
    tos_order_line: tosOrderLine({ ...rawProposal, legs }, quantity, unitLimit),
    exit_targets: proposalExitTargets({ ...rawProposal, legs }, quantity, unitLimit)
  };
}

function proposalExitTargets(proposal, quantity, entryLimit) {
  const existing = Array.isArray(proposal.exit_targets) ? proposal.exit_targets : [];
  const targetPercents = (appState.settings.targets || []).filter(value => Number(value) > 0);
  const percents = targetPercents.length
    ? targetPercents
    : existing.map(target => Number(target.target_percent || 0)).filter(value => value > 0);
  let remaining = quantity;
  return (percents.length ? percents : [20, 50, 60]).slice(0, Math.min(3, quantity)).map((percent, index, targets) => {
    const qty = index === targets.length - 1 ? remaining : 1;
    remaining -= qty;
    let targetLimit = roundMoney(Number(entryLimit || 0) * (1 + Number(percent || 0) / 100));
    if (proposal.structure === "debit_vertical" && Number(proposal.width || 0) > 0) {
      targetLimit = Math.min(targetLimit, Number(proposal.width));
    }
    return {
      qty,
      target_percent: percent,
      target_limit_price: targetLimit,
      estimated_profit: Math.max(0, roundMoney((targetLimit - Number(entryLimit || 0)) * 100 * qty)),
      tos_exit_order_line: tosExitOrderLine(proposal, qty, targetLimit)
    };
  });
}

function renderQuantityControl(proposal) {
  const selected = selectedProposalQuantity(proposal);
  const buttons = Array.from({ length: MAX_PROPOSAL_QUANTITY }, (_value, index) => index + 1).map(quantity => (
    `<button class="segment-button ${quantity === selected ? "active" : ""}" type="button" onclick="setProposalQuantity('${esc(proposal.id)}', ${quantity})">${quantity}</button>`
  )).join("");
  return `<div class="qty-control"><span class="label">Qty</span><span class="segmented">${buttons}</span></div>`;
}

function setProposalQuantity(proposalId, quantity) {
  appState.quantities[proposalId] = Number(quantity);
  render();
}

function proposalTitle(proposal) {
  const legs = proposal.legs || [];
  if (!legs.length) return proposal.structure || "proposal";
  return legs.map(leg => `${leg.action} ${leg.qty} ${leg.symbol} ${leg.expiry} ${formatTosStrike(leg.strike)}${leg.right === "CALL" ? "C" : "P"}`).join(" / ");
}

function proposalMetaText(proposal) {
  const parts = [];
  parts.push(proposalMoneyness(proposal));
  parts.push(proposal.structure || "proposal");
  parts.push(`expiry ${proposal.expiry || "--"}`);
  if (proposal.underlying_price != null) parts.push(`underlying ${Number(proposal.underlying_price).toFixed(2)}`);
  parts.push(`score ${Number(proposal.score || 0).toFixed(2)}`);
  return parts.join(" | ");
}

function proposalLegText(leg) {
  const side = leg.right === "CALL" ? "C" : "P";
  const price = Number(leg.price || leg.ask || leg.mark || 0).toFixed(2);
  return `${leg.action} ${leg.qty} ${leg.symbol} ${leg.expiry} ${formatTosStrike(leg.strike)}${side} @ ${price} | Open Int ${intFmt(leg.open_interest)} | Volume ${intFmt(leg.volume)}`;
}

function proposalEntryLimitText(proposal) {
  const natural = Number(proposal.natural_limit_price || 0);
  const naturalDebit = Number(proposal.natural_debit || 0);
  const sendLimit = Number(proposal.send_limit_price || 0);
  const label = proposal.structure === "single" ? "Ask" : "Natural debit";
  const parts = [];
  if (natural > 0) parts.push(`${label}: ${natural.toFixed(2)}`);
  if (naturalDebit > 0) parts.push(`Natural max: $${naturalDebit.toFixed(2)}`);
  if (sendLimit > 0) parts.push(`Send Limit: ${sendLimit.toFixed(2)}`);
  if (natural > 0) parts.push(`Marketable limit: natural ${natural.toFixed(2)} + ${(Number(appState.settings.entryOffsetCents || 0) / 100).toFixed(2)}`);
  if (proposal.price_protection) parts.push(proposal.price_protection);
  return parts.join(" | ");
}

function proposalExecutionBadge(proposal) {
  if (isSimProposal(proposal)) return badge("SIM ONLY", "amber");
  return liveGateOpen() ? badge("LIVE READY", "red") : badge("DRY RUN", "green");
}

function renderScoreBreakdown(proposal) {
  const rows = Array.isArray(proposal.score_breakdown) ? proposal.score_breakdown.filter(r => r && r.kind === "base") : [];
  if (!rows.length) return "";
  const total = rows.reduce((sum, r) => sum + Number(r.value || 0), 0);
  const items = rows.map(r => `<div class="sb-row"><span>${esc(r.label)}</span><span class="sb-val">${Number(r.value).toFixed(0)}/${r.max}</span></div>`).join("");
  return `<div class="score-breakdown-box"><div class="sb-head">Score breakdown</div>${items}<div class="sb-row sb-total"><span>Total</span><span class="sb-val">${total.toFixed(0)}/100</span></div></div>`;
}

function renderGexWalls(proposal) {
  const t = proposal.gex_target_underlying, s = proposal.gex_stop_underlying, sl = proposal.gex_stop_loss_dollars;
  if (t == null && s == null) return "";
  const stopVal = s == null ? "--" : Number(s).toFixed(2);
  const cap = sl ? ` · ${moneySigned(-Math.abs(Number(sl)))}` : "";
  return `<div class="gex-walls">
    <div class="gex-box target"><div class="label">TARGET · CALL WALL</div><div class="value">${t == null ? "--" : Number(t).toFixed(2)}</div></div>
    <div class="gex-box stop"><div class="label">STOP · PUT WALL (CAPPED)</div><div class="value">${stopVal}${cap}</div></div>
  </div>`;
}

// Platform-style confidence score circle (high/mid/low). Visual only.
function renderScoreCircle(proposal) {
  const s = Number(proposal.score);
  if (!Number.isFinite(s) || s <= 0) return "";
  const cls = s >= 80 ? "high" : (s >= 60 ? "mid" : "low");
  return `<div class="score-badge ${cls}" title="Confidence score"><div class="score-num">${Math.round(s)}</div><div class="score-cap">score</div></div>`;
}

function proposalCard(rawProposal, index) {
  const proposal = adjustedProposalForQuantity(rawProposal);
  const sim = isSimProposal(proposal);
  const legs = (proposal.legs || []).map(leg => `<div class="leg">${esc(proposalLegText(leg))}</div>`).join("");
  const entryLimit = proposalEntryLimitText(proposal);
  const active = index === appState.selectedProposalIndex;
  const moneyness = proposalMoneyness(proposal);
  return `<article class="proposal-card ${sim ? "sim" : ""}" id="proposal-${index}">
    <div class="proposal-top">
      <div>
        <div class="trade-labels"><div class="trade-number">Trade #${index + 1}</div><span class="trade-moneyness">${badge(moneyness, moneynessTone(moneyness))}</span></div>
        <div class="proposal-name">${esc(proposalTitle(proposal))}</div>
        <div class="proposal-meta">${esc(proposalMetaText(proposal))}${active ? " | selected" : ""}</div>
        ${renderQuantityControl(proposal)}
      </div>
      <div class="proposal-side">
        ${renderScoreCircle(proposal)}
        ${proposalExecutionBadge(proposal)}
      </div>
    </div>
    <div class="proposal-stats">
      <div class="metric"><div class="label">Underlying</div><div class="value">${plainMoney(proposal.underlying_price)}</div></div>
      <div class="metric"><div class="label">Debit</div><div class="value">${money(proposal.debit)}</div></div>
      <div class="metric"><div class="label">Max Loss</div><div class="value">${money(proposal.max_loss)}</div></div>
    </div>
    ${renderGexWalls(proposal)}
    ${renderScoreBreakdown(proposal)}
    ${entryLimit ? `<div class="order-note"><span class="label">Entry Limit</span> ${esc(entryLimit)}</div>` : ""}
    <div class="legs">${legs}</div>
    <div class="reasons">${reasonBadges(proposal.reasons, sim ? "amber" : "green")}</div>
    <div class="note-list">${(proposal.notes || []).map(note => `<div>${esc(note)}</div>`).join("")}</div>
    <div class="tos-head">
      <div class="label">TOS Format - TOS Order Entry</div>
      <div class="tos-actions">
        <button onclick="copyProposalTos(${index})">Copy TOS</button>
        <button class="${sim ? "" : "good"}" onclick="sendProposal(${index})" ${sim ? "disabled" : ""}>${sim ? "Send blocked" : "Send to Schwab"}</button>
      </div>
    </div>
    <div class="order-line" id="tos-${index}">${esc(proposal.tos_order_line || "")}</div>
    ${renderExitPlan(proposal, index)}
    ${renderAccountRouting(proposal, index)}
    <div class="send-status" data-send-status-for="${esc(proposal.id)}">${esc(sendStatusText(appState.sendResponses[proposal.id]))}</div>
  </article>`;
}

function firstFilledExitTarget(orderStatus, targetIndex) {
  if (!orderStatus || !Array.isArray(orderStatus.account_statuses)) return null;
  for (const account of orderStatus.account_statuses) {
    if (!["filled", "partial"].includes(account.status) || !account.average_fill_price) continue;
    const target = (account.exit_targets || []).find(item => Number(item.target_index) === Number(targetIndex));
    if (target) return { ...target, account };
  }
  return null;
}

function renderOrderStatusLine(orderStatus) {
  if (!orderStatus) return `<div class="order-note">Entry order fill has not been checked yet.</div>`;
  const rows = (orderStatus.account_statuses || []).map(account => {
    const fill = account.average_fill_price
      ? `fill ${Number(account.average_fill_price).toFixed(2)} x ${Number(account.filled_quantity || 0).toLocaleString()}`
      : `filled ${Number(account.filled_quantity || 0).toLocaleString()}`;
    const broker = account.broker_order_id ? `order ${account.broker_order_id}` : "order id missing";
    const notes = (account.notes || []).join(" | ");
    const statusTone = ["filled", "partial"].includes(account.status) ? "good-text" : account.status === "error" ? "bad-text" : "warn-text";
    return `<div><strong>${esc(account.account_label || account.account_id)}</strong> <span class="${statusTone}">${esc(account.status || "unknown")}</span> | ${esc(broker)} | ${esc(fill)}${notes ? ` | ${esc(notes)}` : ""}</div>`;
  }).join("");
  const notes = (orderStatus.notes || []).map(note => `<div>${esc(note)}</div>`).join("");
  if (!rows && !notes) return `<div class="order-note">No submitted entry order was found for this proposal yet.</div>`;
  return `<div class="order-note">${rows || notes}</div>`;
}

function renderExitPlan(proposal, cardIndex) {
  const targets = Array.isArray(proposal.exit_targets) ? proposal.exit_targets : [];
  if (!targets.length) return "";
  const orderStatus = appState.orderStatuses[proposal.id] || null;
  const hasFill = Boolean(orderStatus?.has_filled_accounts);
  const rows = targets.map((target, index) => {
    const filledTarget = firstFilledExitTarget(orderStatus, index);
    const exitKey = `${proposal.id}:${index}`;
    const exitSendStatus = sendStatusText(appState.exitSendResponses[exitKey]);
    const source = filledTarget || target;
    const qty = Number(target.qty || 1);
    const filledQty = Number(source.qty || qty || 1);
    const percent = Number(source.target_percent || 0);
    const limit = Number(source.target_limit_price || 0);
    const profit = Number(source.estimated_profit || 0);
    const sellLine = source.tos_exit_order_line || tosExitOrderLine(proposal, filledQty, limit);
    const stopTrigger = Number(source.stop_trigger_price || 0);
    const stopLine = source.tos_stop_order_line || "";
    const stopText = stopTrigger > 0 ? ` | Stop @${stopTrigger.toFixed(2)}` : "";
    const rowLabel = filledTarget
      ? `${filledQty} @ +${percent.toLocaleString(undefined, { maximumFractionDigits: 4 })}% -> ${limit.toFixed(2)} | est +$${profit.toFixed(2)}${stopText} | ${filledTarget.account.account_label}`
      : `${qty} @ +${percent.toLocaleString(undefined, { maximumFractionDigits: 4 })}% -> ${limit.toFixed(2)} | est +$${profit.toFixed(2)}${stopText} | planned`;
    return `<div class="exit-target">
      ${esc(rowLabel)}
      <span class="exit-order-line" id="exit-line-${cardIndex}-${index}">${esc(sellLine)}</span>
      ${stopTrigger > 0 && stopLine ? `<span class="exit-order-line">${esc(stopLine)}</span>` : ""}
      <div class="exit-actions">
        <button onclick="copyText(byId('exit-line-${cardIndex}-${index}').textContent)" ${filledTarget ? "" : "disabled"}>Copy SELL</button>
        <button class="${filledTarget ? "good" : ""}" onclick="sendExitTarget(${cardIndex}, ${index})" ${filledTarget ? "" : "disabled"}>${filledTarget ? "Send SELL" : "Get fill first"}</button>
      </div>
      <div class="send-status" data-exit-status-for="${esc(exitKey)}">${esc(exitSendStatus)}</div>
    </div>`;
  }).join("");
  return `<div class="exit-plan">
    <div class="exit-row"><div><span class="label">Exit Plan</span> <span class="${hasFill ? "good-text" : "warn-text"}">${hasFill ? "fill-based closing order ready" : "target exits not sent yet"}</span></div><button onclick="refreshProposalOrderStatus('${esc(proposal.id)}', this)">Get Order Info</button></div>
    ${renderOrderStatusLine(orderStatus)}
    <div class="exit-targets">${rows}</div>
  </div>`;
}

async function sendExitTarget(cardIndex, targetIndex) {
  const rawProposal = appState.currentProposals[cardIndex];
  if (!rawProposal) return;
  const proposal = adjustedProposalForQuantity(rawProposal);
  const exitKey = `${proposal.id}:${targetIndex}`;
  const status = document.querySelector(`[data-exit-status-for="${CSS.escape(exitKey)}"]`);
  const orderStatus = appState.orderStatuses[proposal.id] || await refreshProposalOrderStatus(proposal.id, null);
  const filledTarget = firstFilledExitTarget(orderStatus, targetIndex);
  if (!filledTarget) {
    if (status) status.textContent = "Get Order Info first; no filled entry target is available yet.";
    return;
  }
  const selectedIds = Array.from(appState.selectedAccountIds);
  if (!selectedIds.length) {
    if (!appState.accounts.length) await loadAccounts();
    if (status) status.textContent = "Select at least one Schwab account before sending a closing order.";
    return;
  }
  const sellLine = filledTarget.tos_exit_order_line || byId(`exit-line-${cardIndex}-${targetIndex}`)?.textContent || "";
  let confirmLiveOrder = false;
  if (liveGateOpen()) {
    confirmLiveOrder = window.confirm(`Submit LIVE Schwab closing order?\\n\\n${sellLine}\\nAccounts: ${selectedIds.join(", ")}\\n\\nOnly continue if this is exactly the closing order you want.`);
    if (!confirmLiveOrder) {
      if (status) status.textContent = "Live closing order cancelled before submission.";
      return;
    }
  }
  if (status) status.textContent = "Sending closing order...";
  const body = {
    selected_account_ids: selectedIds,
    confirm_live_order: confirmLiveOrder,
    order_note: `Schwab Market Scanner EXIT | ${proposal.symbol} target #${targetIndex + 1}`
  };
  const targets = encodeURIComponent((appState.settings.targets || [20, 50, 60]).join(","));
  const result = await fetchJson(`/proposals/${encodeURIComponent(proposal.id)}/targets/${targetIndex}/send?target_percentages=${targets}`, authOptions("POST", body));
  if (!result.ok) {
    if (status) status.textContent = result.data?.detail || result.data?.body || `HTTP ${result.status}`;
    return;
  }
  appState.exitSendResponses[exitKey] = result.data;
  if (Array.isArray(result.data.selected_account_ids)) {
    appState.selectedAccountIds = new Set(result.data.selected_account_ids);
  }
  render();
}

async function refreshProposalOrderStatus(proposalId, button) {
  if (!proposalId) return null;
  const original = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "Checking...";
  }
  byId("proposal-status").textContent = "checking order";
  try {
    const targets = encodeURIComponent((appState.settings.targets || [20, 50, 60]).join(","));
    const result = await fetchJson(`/proposals/${encodeURIComponent(proposalId)}/orders/status?target_percentages=${targets}`);
    if (!result.ok) {
      const detail = result.data?.detail || result.data?.body || `HTTP ${result.status}`;
      byId("proposal-notice").className = "notice red";
      byId("proposal-notice").textContent = `Order info failed: ${detail}`;
      byId("proposal-status").textContent = "order check failed";
      return null;
    }
    appState.orderStatuses[proposalId] = result.data;
    render();
    return result.data;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original || "Get Order Info";
    }
  }
}

function proposalRequiredCost(proposal) {
  const maxLoss = Number(proposal?.max_loss || 0);
  const debit = Number(proposal?.debit || 0);
  if (Number.isFinite(maxLoss) && maxLoss > 0) return maxLoss;
  if (Number.isFinite(debit) && debit > 0) return debit;
  return 0;
}

function accountBalanceInfo(account, proposal) {
  const balance = account?.balance || null;
  const required = proposalRequiredCost(proposal);
  if (!balance || !Object.keys(balance).length) {
    return { tone: "gray", routeClass: "", label: "Avail --", meta: "balance unavailable" };
  }
  if (balance.error) {
    return { tone: "red", routeClass: "balance-low", label: "Balance error", meta: "balance lookup failed" };
  }
  const available = Number(balance.available_to_trade);
  if (!Number.isFinite(available)) {
    return { tone: "gray", routeClass: "", label: "Avail --", meta: "available balance unavailable" };
  }
  const ok = required <= 0 || available >= required;
  const buyingPower = Number(balance.buying_power);
  const cashBalance = Number(balance.cash_balance);
  const needText = required > 0 ? ` | needed ${money(required)}` : "";
  const buyingPowerText = Number.isFinite(buyingPower) ? ` | buying power ${money(buyingPower)}` : "";
  const cashText = Number.isFinite(cashBalance) ? ` | cash ${money(cashBalance)}` : "";
  return {
    tone: ok ? "green" : "red",
    routeClass: ok ? "balance-ok" : "balance-low",
    label: `Avail ${money(available)}`,
    meta: `available ${money(available)}${needText}${buyingPowerText}${cashText}`,
  };
}

function renderAccountRouting(proposal, index) {
  const accounts = appState.accounts || [];
  if (appState.accountsLoading) {
    return `<div class="accounts">
      <div class="accounts-head"><div class="label">Accounts to Send</div><button disabled>Loading...</button></div>
      <div class="account-list"><div class="muted">Fetching Schwab accounts...</div></div>
    </div>`;
  }
  if (!accounts.length) {
    const notes = (appState.accountNotes || []).join(" ");
    return `<div class="accounts">
      <div class="accounts-head"><div class="label">Accounts to Send</div><button onclick="loadAccounts()">Load Accounts</button></div>
      <div class="account-list"><div class="muted">${esc(notes || "No accounts loaded yet.")}</div></div>
    </div>`;
  }
  const rows = accounts.map(account => {
    const disabled = !account.enabled || (proposal.structure === "debit_vertical" && !account.supports_spreads);
    const balanceInfo = accountBalanceInfo(account, proposal);
    const selected = appState.selectedAccountIds.has(account.id) || (!appState.selectedAccountIds.size && account.default_selected);
    const spread = account.supports_spreads ? "spread ok" : "single-leg only";
    const configured = account.order_configured ? "order hash set" : "order hash missing";
    return `<label class="account-row ${disabled ? "disabled" : balanceInfo.routeClass}">
      <input type="checkbox" data-account-id="${esc(account.id)}" onchange="toggleAccount(this)" ${selected && !disabled ? "checked" : ""} ${disabled ? "disabled" : ""}>
      <span><strong>${esc(account.account_number || account.id)} (${esc(account.label || account.id)})</strong> <span class="muted">${esc(account.account_type || "account")} | ${spread} | ${configured} | ${esc(account.source || "discovered")} | ${esc(balanceInfo.meta)}</span></span>
      ${disabled ? badge("Blocked", "red") : badge(balanceInfo.label, balanceInfo.tone)}
    </label>`;
  }).join("");
  return `<div class="accounts">
    <div class="accounts-head"><div class="label">Accounts to Send</div><button onclick="loadAccounts({force:true})">Refresh Accounts</button></div>
    <div class="account-list">${rows}</div>
  </div>`;
}

async function loadAccounts(options = {}) {
  const force = Boolean(options.force);
  const key = "dashboard-open-access";
  if (appState.accountsLoading) return;
  if (!force && appState.accountsLoadedForKey === key) return;
  const opts = authOptions("GET");
  if (!opts) return;
  appState.accountsLoading = true;
  render();
  let result;
  try {
    result = await fetchJson("/accounts", opts);
  } catch (error) {
    appState.accountNotes = [`Account fetch failed: ${error.message}`];
    appState.accounts = [];
    appState.accountsLoadedForKey = "";
    appState.accountsLoading = false;
    render();
    return;
  }
  if (!result.ok) {
    appState.accountNotes = [result.data?.detail || result.data?.body || `HTTP ${result.status}`];
    appState.accounts = [];
    appState.accountsLoadedForKey = "";
    appState.accountsLoading = false;
    render();
    return;
  }
  appState.accounts = result.data.accounts || [];
  appState.accountNotes = result.data.notes || [];
  appState.accountsLoadedForKey = key;
  appState.accountsLoading = false;
  // Preserve the operator's current selection across refreshes; only fall back to defaults on
  // the first load (empty selection). Drop any selected id that no longer exists/enabled.
  const enabledIds = new Set(appState.accounts.filter(a => a.enabled).map(a => a.id));
  const existing = (appState.selectedAccountIds && appState.selectedAccountIds.size)
    ? new Set([...appState.selectedAccountIds].filter(id => enabledIds.has(id)))
    : null;
  appState.selectedAccountIds = (existing && existing.size)
    ? existing
    : new Set(appState.accounts.filter(account => account.default_selected && account.enabled).map(account => account.id));
  render();
}

function toggleAccount(checkbox) {
  const id = checkbox.dataset.accountId || "";
  if (!id) return;
  if (checkbox.checked) appState.selectedAccountIds.add(id);
  else appState.selectedAccountIds.delete(id);
}

async function sendProposal(index) {
  const rawProposal = appState.currentProposals[index];
  if (!rawProposal) return;
  const proposal = adjustedProposalForQuantity(rawProposal);
  const sim = isSimProposal(proposal);
  const status = document.querySelector(`[data-send-status-for="${CSS.escape(proposal.id)}"]`);
  if (sim) {
    if (status) status.textContent = "SIM_ONLY proposals are blocked from Schwab order submission.";
    return;
  }
  const selectedIds = Array.from(appState.selectedAccountIds);
  if (!selectedIds.length) {
    if (!appState.accounts.length) await loadAccounts();
    if (status) status.textContent = "Select at least one Schwab account before sending.";
    return;
  }
  // OTOCO only applies to single-leg entries; the backend falls back to a plain entry otherwise.
  const otoco = Boolean(appState.settings.otoco) && proposal.structure === "single";
  let confirmLiveOrder = false;
  if (liveGateOpen()) {
    const otocoLine = otoco ? "\\nOTOCO: entry placed as bracketed slices — target + stop attach at Schwab and activate on fill." : "";
    confirmLiveOrder = window.confirm(`Submit LIVE Schwab order?\\n\\n${proposal.tos_order_line}\\nAccounts: ${selectedIds.join(", ")}\\nMax loss: ${money(proposal.max_loss)}${otocoLine}\\n\\nOnly continue if this is exactly the trade you want.`);
    if (!confirmLiveOrder) {
      if (status) status.textContent = "Live order cancelled before submission.";
      return;
    }
  }
  if (status) status.textContent = "Checking selected accounts...";
  const body = {
    selected_account_ids: selectedIds,
    confirm_live_order: confirmLiveOrder,
    quantity: proposal.quantity,
    limit_price: proposal.send_limit_price,
    otoco: otoco,
    order_note: `Schwab Market Scanner | ${proposal.symbol} ${proposal.direction || ""} | ${proposalMoneyness(proposal)}`
  };
  const opts = authOptions("POST", body);
  const targets = encodeURIComponent((appState.settings.targets || [20, 50, 60]).join(","));
  const result = await fetchJson(`/proposals/${encodeURIComponent(proposal.id)}/send?target_percentages=${targets}`, opts);
  if (!result.ok) {
    if (status) status.textContent = result.data?.detail || result.data?.body || `HTTP ${result.status}`;
    return;
  }
  appState.sendResponses[proposal.id] = result.data;
  delete appState.orderStatuses[proposal.id];
  if (Array.isArray(result.data.selected_account_ids)) {
    appState.selectedAccountIds = new Set(result.data.selected_account_ids);
  }
  render();
  // Auto-check fill status after a live submission (no need to click "Get Order Info").
  const submitted = result.data.status === "submitted"
    || (result.data.account_results || []).some(r => r.status === "submitted");
  if (submitted) autoCheckOrderStatus(proposal.id);
}

async function autoCheckOrderStatus(proposalId) {
  // Poll the entry-order status a few times after sending, stopping once an account fills.
  // Guarded so repeated sends don't stack overlapping pollers.
  if (!appState._autoChecks) appState._autoChecks = new Set();
  if (appState._autoChecks.has(proposalId)) return;
  appState._autoChecks.add(proposalId);
  try {
    const delays = [2500, 4000, 6000, 10000, 15000, 30000];
    for (const wait of delays) {
      await new Promise(resolve => setTimeout(resolve, wait));
      if (!appState.sendResponses[proposalId]) return;  // proposal cleared/rebuilt
      const data = await refreshProposalOrderStatus(proposalId, null);
      if (data && data.has_filled_accounts) return;     // filled -> stop polling
    }
  } finally {
    appState._autoChecks.delete(proposalId);
  }
}

function sendStatusText(response) {
  if (!response) return "";
  const results = response.account_results || [];
  const notes = (response.notes || []).join(" ");
  if (!results.length) return notes;
  const accountText = results.map(item => {
    const reasons = (item.reasons || []).join(", ") || item.status;
    const broker = item.broker_order_id ? ` ${item.broker_order_id}` : "";
    return `${item.account_label}: ${item.status}${broker} (${reasons})`;
  }).join(" | ");
  return `${accountText}${notes ? " | " + notes : ""}`;
}

async function copyText(text) {
  const value = String(text || "");
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    document.body.removeChild(textarea);
  }
  setStatus("Copied TOS line");
}

function copyProposalTos(index) {
  const proposal = adjustedProposalForQuantity(appState.currentProposals[index]);
  if (proposal?.tos_order_line) copyText(proposal.tos_order_line);
}

function copySelectedTos() {
  const first = appState.currentProposals[appState.selectedProposalIndex] || appState.currentProposals[0];
  if (first) copyProposalTos(appState.currentProposals.indexOf(first));
}

function showFirstProposal() {
  const first = byId("proposal-0");
  if (first) first.scrollIntoView({ behavior: "smooth", block: "start" });
}

function soundReady() {
  appState.soundArmed = true;
  byId("proposal-status").textContent = "sound ready";
}

function testSound() {
  try {
    const context = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.001, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.12, context.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.22);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.25);
    byId("proposal-status").textContent = "sound tested";
  } catch {
    byId("proposal-status").textContent = "sound unavailable";
  }
}

load();
setInterval(load, 60000);
setInterval(() => loadPositions(false), 15000);
</script>
</body>
</html>"""
