from __future__ import annotations


def dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Schwab Market Scanner</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --bg: #f3f6fa;
      --panel: #ffffff;
      --ink: #111827;
      --muted: #657188;
      --line: #dbe3ed;
      --line-soft: #edf1f6;
      --blue: #2563eb;
      --green: #0f7a3b;
      --green-bg: #ecfdf3;
      --amber: #b45309;
      --amber-bg: #fff7ed;
      --red: #a51616;
      --red-bg: #fff1f2;
      --navy: #111827;
      --slate-bg: #f8fafc;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--ink); }
    button, input { font: inherit; }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 7px;
      padding: 9px 13px;
      cursor: pointer;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
      color: var(--ink);
    }
    button.primary { background: var(--blue); border-color: var(--blue); color: white; font-weight: 800; }
    button.good { background: var(--green-bg); border-color: #bbf7d0; color: var(--green); font-weight: 800; }
    button.danger { background: var(--red-bg); border-color: #fecdd3; color: var(--red); font-weight: 800; }
    button.ghost { background: #f8fafc; }
    button.sound { background: var(--green-bg); border-color: #bbf7d0; color: var(--green); font-weight: 900; }
    button:disabled { cursor: not-allowed; color: #94a3b8; background: #f8fafc; }
    input {
      border: 1px solid var(--line);
      background: white;
      border-radius: 7px;
      padding: 9px 11px;
      min-width: 230px;
    }
    .page { max-width: 1880px; margin: 0 auto; padding: 22px; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
    .title h1 { margin: 0; font-size: 23px; line-height: 1.1; letter-spacing: 0; }
    .title .sub { margin-top: 6px; color: var(--muted); font-size: 14px; }
    .top-actions { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; justify-content: flex-end; }
    .layout { display: grid; grid-template-columns: minmax(500px, 540px) minmax(0, 1fr); gap: 6px; align-items: start; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .panel + .panel { margin-top: 12px; }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 15px;
      border-bottom: 1px solid var(--line-soft);
    }
    .panel-head h2 { margin: 0; font-size: 16px; }
    .panel-title { font-size: 16px; font-weight: 900; }
    .panel-body { padding: 14px 15px; }
    .kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 7px; margin-bottom: 10px; }
    .kpi { min-height: 72px; padding: 10px 9px; background: white; border: 1px solid var(--line); border-radius: 8px; }
    .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0; }
    .kpi .value { margin-top: 7px; font-size: 16px; font-weight: 900; overflow-wrap: anywhere; }
    .state-summary {
      padding: 9px 15px 11px;
      border-top: 1px solid var(--line-soft);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .badges { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 13px;
      font-weight: 900;
      background: #eef2ff;
      color: #1d4ed8;
      border: 1px solid #dbeafe;
      white-space: nowrap;
    }
    .badge.green { background: var(--green-bg); color: var(--green); border-color: #bbf7d0; }
    .badge.amber { background: var(--amber-bg); color: var(--amber); border-color: #fed7aa; }
    .badge.red { background: var(--red-bg); color: var(--red); border-color: #fecdd3; }
    .badge.gray { background: #f8fafc; color: #475569; border-color: var(--line); }
    .notice { border-left: 4px solid var(--amber); background: #fff7ed; padding: 12px 14px; border-radius: 7px; color: #7c3f06; line-height: 1.45; }
    .notice.green { border-left-color: var(--green); background: var(--green-bg); color: #14532d; }
    .notice.red { border-left-color: var(--red); background: var(--red-bg); color: var(--red); }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
    .table-wrap table { min-width: 620px; }
    th, td { text-align: left; padding: 11px 10px; border-bottom: 1px solid var(--line-soft); vertical-align: top; font-size: 14px; }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; background: #f8fafc; }
    tr.candidate-row { cursor: pointer; }
    tr.candidate-row.selected { background: #ecfdf3; box-shadow: inset 4px 0 0 var(--green); }
    .sym { font-weight: 900; }
    .tiny { font-size: 12px; color: var(--muted); }
    .muted { color: var(--muted); }
    .good-text { color: var(--green); }
    .bad-text { color: var(--red); }
    .warn-text { color: var(--amber); }
    .right-panel { position: sticky; top: 14px; }
    .right-panel .panel-head { padding: 10px 12px; }
    .right-panel .panel-body { padding: 10px 12px; }
    .right-panel button { padding: 6px 9px; font-size: 13px; }
    .proposal-toolbar { display: grid; grid-template-columns: minmax(160px, 0.7fr) minmax(430px, auto); gap: 8px; align-items: start; }
    .proposal-title h2 { margin: 0 0 5px; font-size: 16px; }
    .right-panel .proposal-title h2 { font-size: 15px; }
    .proposal-controls { display: flex; gap: 5px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
    .proposal-settings { display: inline-flex; gap: 5px; align-items: center; flex-wrap: nowrap; }
    .setting-label { color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; }
    .segmented { display: inline-flex; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: white; }
    .segment-button {
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
      box-shadow: none;
      min-width: 46px;
      padding: 6px 8px;
      background: white;
      font-weight: 800;
      font-size: 13px;
    }
    .segment-button:last-child { border-right: 0; }
    .segment-button.active { background: var(--green-bg); color: var(--green); }
    .checkbox-setting { display: inline-flex; align-items: center; gap: 5px; font-weight: 900; font-size: 13px; }
    .checkbox-setting input { min-width: 0; width: 17px; height: 17px; accent-color: var(--green); }
    .target-inputs { display: inline-flex; gap: 4px; }
    .target-inputs input { min-width: 0; width: 46px; font-weight: 900; text-align: center; padding: 6px 7px; font-size: 13px; }
    .moneyness-strip { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
    .right-panel .moneyness-strip .badge { min-height: 22px; padding: 3px 7px; font-size: 11px; }
    .candidate-summary, .freshness { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 9px 0; }
    .freshness { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfdff; min-width: 0; }
    .metric .value { margin-top: 7px; font-size: 18px; font-weight: 900; overflow-wrap: anywhere; }
    .right-panel .metric { padding: 8px 9px; min-height: 58px; }
    .right-panel .metric .label { font-size: 11px; }
    .right-panel .metric .value { margin-top: 4px; font-size: 15px; }
    .right-panel .notice { padding: 9px 11px; font-size: 13px; line-height: 1.35; }
    .proposal-card {
      border: 1px solid #bbf7d0;
      border-left: 4px solid var(--green);
      border-radius: 8px;
      background: var(--green-bg);
      padding: 10px 12px;
      margin-top: 9px;
    }
    .proposal-card.sim { border-color: #fed7aa; border-left-color: var(--amber); background: #fffaf0; }
    .proposal-top { display: flex; align-items: start; justify-content: space-between; gap: 8px; }
    .trade-labels { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .trade-number { display: inline-flex; align-items: center; min-height: 24px; border-radius: 6px; padding: 3px 8px; background: var(--green); color: white; font-size: 12px; font-weight: 900; }
    .proposal-card.sim .trade-number { background: var(--amber); }
    .trade-moneyness { font-size: 13px; }
    .trade-moneyness .badge { min-height: 24px; padding: 3px 8px; font-size: 12px; }
    .proposal-name { margin-top: 6px; font-weight: 900; font-size: 15px; }
    .proposal-meta { margin-top: 3px; color: var(--muted); font-size: 12px; }
    .proposal-card .metric { padding: 8px; }
    .proposal-card .metric .value { margin-top: 4px; font-size: 16px; }
    .proposal-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin-top: 8px; }
    .qty-control { display: flex; gap: 6px; align-items: center; margin-top: 8px; flex-wrap: wrap; }
    .qty-control .segment-button { min-width: 34px; padding: 6px 8px; }
    .order-note { margin-top: 8px; color: var(--muted); line-height: 1.35; font-size: 12px; }
    .legs { margin-top: 7px; display: grid; gap: 4px; }
    .leg {
      background: #e8edf5;
      color: var(--ink);
      border-radius: 6px;
      padding: 7px 9px;
      overflow-x: auto;
      white-space: pre;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }
    .tos-head, .exit-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 9px; }
    .tos-actions, .exit-actions { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
    .order-line {
      margin-top: 7px;
      background: var(--navy);
      color: white;
      border-radius: 6px;
      padding: 9px 10px;
      overflow-x: auto;
      white-space: pre;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }
    .proposal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; flex-wrap: wrap; }
    .reasons { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 8px; }
    .proposal-card .reasons .badge { min-height: 22px; padding: 3px 7px; font-size: 11px; }
    .note-list { margin-top: 6px; color: var(--muted); font-size: 12px; line-height: 1.35; }
    .exit-plan { border-top: 1px solid var(--line); margin-top: 10px; padding-top: 8px; }
    .exit-targets { display: grid; gap: 6px; margin-top: 6px; }
    .exit-target { font-weight: 900; font-size: 12px; }
    .exit-order-line {
      display: block;
      margin-top: 5px;
      background: #e5e7eb;
      border-radius: 6px;
      padding: 7px 9px;
      overflow-x: auto;
      white-space: pre;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
      font-weight: 500;
    }
    .accounts { border: 1px solid var(--line); border-radius: 8px; margin-top: 9px; background: rgba(255, 255, 255, 0.62); }
    .accounts-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 9px; border-bottom: 1px solid var(--line-soft); }
    .account-list { display: grid; gap: 6px; padding: 8px; }
    .account-row {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 9px;
      background: white;
      font-size: 12px;
    }
    .account-row.disabled { background: var(--red-bg); border-color: #fecdd3; }
    .account-row input { min-width: 0; width: 18px; height: 18px; accent-color: var(--blue); }
    .send-status { margin-top: 8px; font-size: 13px; color: var(--muted); overflow-wrap: anywhere; }
    .empty { padding: 14px; color: var(--muted); text-align: center; border: 1px dashed var(--line); border-radius: 8px; background: #fbfdff; font-size: 12px; line-height: 1.35; }
    @media (max-width: 1180px) {
      .layout { grid-template-columns: 1fr; }
      .right-panel { position: static; }
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .proposal-toolbar { grid-template-columns: 1fr; }
      .proposal-controls { justify-content: flex-start; }
    }
    @media (max-width: 760px) {
      .page { padding: 14px; }
      .topbar { align-items: stretch; flex-direction: column; }
      .top-actions, .proposal-controls { justify-content: stretch; }
      .top-actions > *, .proposal-controls > * { flex: 1 1 auto; }
      input { min-width: 0; width: 100%; }
      .candidate-summary, .proposal-stats, .freshness { grid-template-columns: 1fr; }
      .kpis { grid-template-columns: 1fr; }
      .account-row { grid-template-columns: auto 1fr; }
      .account-row .badge { grid-column: 1 / -1; }
    }
  </style>
</head>
<body>
  <main class="page">
    <section class="topbar">
      <div class="title">
        <h1>Schwab Market Scanner</h1>
        <div class="sub" id="last-update">Loading...</div>
      </div>
      <div class="top-actions">
        <button class="ghost" onclick="load()">Refresh</button>
        <button class="ghost" id="refresh-prices-button" data-run-scan-button onclick="runScan(false)">Refresh Prices</button>
        <button class="primary" id="run-scan-button" data-run-scan-button onclick="runScan(true)">Run Scan</button>
      </div>
    </section>

    <section class="layout">
      <div>
        <div class="kpis">
          <div class="kpi"><div class="label">Service</div><div class="value" id="kpi-service">...</div></div>
          <div class="kpi"><div class="label">Schwab Data</div><div class="value" id="kpi-schwab">...</div></div>
          <div class="kpi"><div class="label">Mode</div><div class="value" id="kpi-mode">...</div></div>
          <div class="kpi"><div class="label">Regime</div><div class="value" id="kpi-regime">...</div></div>
          <div class="kpi"><div class="label">Proposals</div><div class="value" id="kpi-proposals">...</div></div>
        </div>

        <section class="panel">
          <div class="panel-head">
            <h2>Operating State</h2>
            <div class="badges" id="state-badges"></div>
          </div>
          <div class="state-summary" id="state-summary" title="">Loading scanner state...</div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <h2>Top Candidates</h2>
            <div class="muted" id="candidate-count">0 shown</div>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style="width: 17%;">Symbol</th>
                  <th style="width: 14%;">Bias</th>
                  <th style="width: 13%;">Price</th>
                  <th style="width: 12%;">Gap</th>
                  <th style="width: 16%;">PM Vol</th>
                  <th style="width: 14%;">Proposals</th>
                  <th>Read</th>
                </tr>
              </thead>
              <tbody id="candidate-rows">
                <tr><td colspan="7" class="muted">Loading...</td></tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section class="panel right-panel">
        <div class="panel-head proposal-toolbar">
          <div class="proposal-title">
            <h2>Current Proposal</h2>
            <div class="muted" id="proposal-subtitle">Select a candidate.</div>
          </div>
          <div class="proposal-controls">
            <span class="muted" id="proposal-status">ready</span>
            <span class="proposal-settings" aria-label="Expiry settings">
              <span class="setting-label">Expiry</span>
              <span class="segmented" id="expiry-buttons" role="group" aria-label="Proposal expiry"></span>
            </span>
            <span class="proposal-settings" aria-label="Moneyness settings">
              <label class="checkbox-setting"><input id="allow-itm-checkbox" type="checkbox" onchange="setAllowItm(this.checked)">ITM</label>
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
              <span class="setting-label">Targets</span>
              <span class="target-inputs" id="target-inputs" role="group" aria-label="Proposal targets"></span>
              <button class="ghost" onclick="applyTargets()">Apply</button>
            </span>
            <button class="sound" onclick="soundReady()">Sound Ready</button>
            <button class="ghost" onclick="testSound()">Test Sound</button>
            <button class="ghost" onclick="showFirstProposal()">Show Proposal</button>
            <button class="ghost" disabled>Mark Reviewed</button>
          </div>
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
  soundArmed: false,
  settings: {
    expiry: "NEXT_WEEK_FRIDAY",
    expiryChoices: ["0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY"],
    allowItm: true,
    maxLoss: 300,
    maxLossChoices: [200, 300, 400, 500],
    entryOffsetCents: 10,
    entryOffsetChoices: [10, 20, 30, 40, 50],
    targets: [25, 50, 60]
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

function authOptions(method, body) {
  const opts = { method, headers: {} };
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
    const label = choice === "THIS_FRIDAY" ? "This Fri" : choice === "NEXT_WEEK_FRIDAY" ? "Next Fri" : choice;
    return `<button class="segment-button ${choice === settings.expiry ? "active" : ""}" type="button" onclick="setExpiry('${esc(choice)}')">${esc(label)}</button>`;
  }).join("");
  byId("allow-itm-checkbox").checked = Boolean(settings.allowItm);
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

function setExpiry(value) {
  appState.settings.expiry = value;
  saveDashboardSettings();
  render();
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
function setAllowItm(value) {
  appState.settings.allowItm = Boolean(value);
  saveDashboardSettings();
  render();
}
function applyTargets() {
  const next = [0, 1, 2].map(index => Number(byId(`target-${index}`)?.value || 0)).filter(value => value > 0);
  appState.settings.targets = next.length ? next : [25, 50, 60];
  saveDashboardSettings();
  render();
}

async function load() {
  loadDashboardSettings();
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
}

async function runScan(includeOptions = true) {
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
    const result = await fetchJson(`/scan/run?include_options=${includeOptions ? "true" : "false"}`, opts);
    renderProtectedResult(result);
  } finally {
    buttons.forEach(button => {
      button.disabled = false;
      button.textContent = button.dataset.originalText || "Run Scan";
    });
  }
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
}

function render() {
  renderSetupControls();
  const health = appState.health || {};
  const config = health.config || {};
  const schwab = appState.schwab || {};
  const scan = appState.scan;
  const proposals = allProposals(scan);

  byId("kpi-service").textContent = health.status || "...";
  byId("kpi-schwab").textContent = schwab.read_only_ready ? "READY" : (schwab.status || "...");
  byId("kpi-mode").textContent = config.execution_mode || "...";
  byId("kpi-regime").textContent = scan?.regime?.bias || "...";
  byId("kpi-proposals").textContent = String(proposals.length);

  const hasSim = proposals.some(isSimProposal);
  byId("state-badges").innerHTML = [
    badge((config.execution_mode || "dry_run").toUpperCase(), config.execution_mode === "live" ? "red" : "gray"),
    badge(config.live_gate_open ? "LIVE GATE ON" : "LIVE GATE OFF", config.live_gate_open ? "red" : "green"),
    badge(schwab.read_only_ready ? "SCHWAB DATA READY" : "SCHWAB DATA WAITING", schwab.read_only_ready ? "green" : "amber"),
    hasSim ? badge("SIM PROPOSALS", "amber") : badge("CURRENT PROPOSALS", "green"),
    badge(appState.settings.allowItm ? "ITM ALLOWED" : "ATM/OTM ONLY", appState.settings.allowItm ? "green" : "gray"),
  ].join("");

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
  byId("candidate-rows").innerHTML = candidates.map(candidateRow).join("") ||
    `<tr><td colspan="7" class="muted">No candidates.</td></tr>`;
  renderProposal(candidates.find(item => item.symbol === appState.selectedSymbol) || candidates[0]);
}

function candidateRow(candidate) {
  const metrics = candidate.metrics || {};
  const selected = candidate.symbol === appState.selectedSymbol ? " selected" : "";
  const proposals = candidateProposals(candidate);
  const tone = candidate.action === "CALL_BIAS" ? "green" : candidate.action === "PUT_BIAS" ? "amber" : "gray";
  const selectedAttr = esc(candidate.symbol).replace(/'/g, "\\'");
  return `<tr class="candidate-row${selected}" onclick="selectCandidate('${selectedAttr}')">
    <td><div class="sym">${esc(candidate.symbol)}</div><div class="tiny">rank ${candidate.rank || ""}</div></td>
    <td>${badge(candidate.action || "WATCH", tone)}</td>
    <td>${plainMoney(metrics.current_price)}</td>
    <td class="${Number(metrics.gap_pct || 0) >= 0 ? "good-text" : "bad-text"}">${pct(metrics.gap_pct)}</td>
    <td>${intFmt(metrics.premarket_volume)}</td>
    <td>${badge(`${proposals.length} ready`, proposals.length ? "green" : "gray")}</td>
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
    byId("proposal-notice").textContent = "Run a full scan to populate proposals.";
    byId("proposal-cards").innerHTML = `<div class="empty">No proposal selected.</div>`;
    renderQuoteFreshness([]);
    setMetrics(null);
    return;
  }
  const metrics = candidate.metrics || {};
  const proposals = candidateProposals(candidate);
  appState.currentProposals = proposals;
  const sim = proposals.some(isSimProposal);
  const moneyness = proposals.map(proposalMoneyness).filter(Boolean);
  const uniqueMoneyness = Array.from(new Set(moneyness)).join(", ") || "ATM/OTM";
  byId("proposal-subtitle").textContent = `${candidate.symbol} ${candidate.action} | ${proposals.length} proposal${proposals.length === 1 ? "" : "s"} | ${uniqueMoneyness}`;
  byId("proposal-status").textContent = proposals.length ? "ready" : "blocked";
  byId("proposal-notice").className = sim ? "notice" : "notice green";
  byId("proposal-notice").textContent = sim
    ? "SIM ONLY: replayed Friday underlying prices with current Schwab option-chain contract data. Order sending is blocked."
    : "Access token is present for read-only market-data calls. Schwab order placement remains controlled by scanner execution gates.";
  setMetrics(metrics);
  renderQuoteFreshness(proposals);
  byId("proposal-cards").innerHTML = proposals.length
    ? proposals.map((proposal, index) => proposalCard(proposal, index)).join("")
    : `<div class="empty">${esc((candidate.proposal_blocked_reasons || ["No proposals for this candidate."]).join(" | "))}</div>`;
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
  if (existing.length) {
    return existing.map(target => ({
      ...target,
      tos_exit_order_line: target.tos_exit_order_line || tosExitOrderLine(proposal, Number(target.qty || 1), Number(target.target_limit_price || entryLimit)),
    }));
  }
  let remaining = quantity;
  return appState.settings.targets.slice(0, Math.min(3, quantity)).map((percent, index, targets) => {
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
      ${proposalExecutionBadge(proposal)}
    </div>
    <div class="proposal-stats">
      <div class="metric"><div class="label">Underlying</div><div class="value">${plainMoney(proposal.underlying_price)}</div></div>
      <div class="metric"><div class="label">Debit</div><div class="value">${money(proposal.debit)}</div></div>
      <div class="metric"><div class="label">Max Loss</div><div class="value">${money(proposal.max_loss)}</div></div>
    </div>
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

function renderExitPlan(proposal, cardIndex) {
  const targets = Array.isArray(proposal.exit_targets) ? proposal.exit_targets : [];
  if (!targets.length) return "";
  const rows = targets.map((target, index) => {
    const qty = Number(target.qty || 1);
    const percent = Number(target.target_percent || 0);
    const limit = Number(target.target_limit_price || 0);
    const profit = Number(target.estimated_profit || 0);
    const sellLine = target.tos_exit_order_line || tosExitOrderLine(proposal, qty, limit);
    return `<div class="exit-target">
      ${esc(`${qty} @ +${percent.toLocaleString(undefined, { maximumFractionDigits: 4 })}% -> ${limit.toFixed(2)} | est +$${profit.toFixed(2)}`)}
      <span class="exit-order-line" id="exit-line-${cardIndex}-${index}">${esc(sellLine)}</span>
      <div class="exit-actions"><button onclick="copyText(byId('exit-line-${cardIndex}-${index}').textContent)">Copy SELL</button><button disabled>Get fill first</button></div>
    </div>`;
  }).join("");
  return `<div class="exit-plan">
    <div class="exit-row"><div><span class="label">Exit Plan</span> <span class="warn-text">target exits not sent yet</span></div><button disabled>Get Order Info</button></div>
    <div class="order-note">Entry order fill has not been checked yet.</div>
    <div class="exit-targets">${rows}</div>
  </div>`;
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
    const selected = appState.selectedAccountIds.has(account.id) || (!appState.selectedAccountIds.size && account.default_selected);
    const spread = account.supports_spreads ? "spread ok" : "single-leg only";
    const configured = account.order_configured ? "order hash set" : "order hash missing";
    return `<label class="account-row ${disabled ? "disabled" : ""}">
      <input type="checkbox" data-account-id="${esc(account.id)}" onchange="toggleAccount(this)" ${selected && !disabled ? "checked" : ""} ${disabled ? "disabled" : ""}>
      <span><strong>${esc(account.account_number || account.id)} (${esc(account.label || account.id)})</strong> <span class="muted">${esc(account.account_type || "account")} | ${spread} | ${configured} | ${esc(account.source || "discovered")}</span></span>
      ${disabled ? badge("Blocked", "red") : badge("Ready", "green")}
    </label>`;
  }).join("");
  return `<div class="accounts">
    <div class="accounts-head"><div class="label">Accounts to Send</div><button onclick="loadAccounts()">Refresh Accounts</button></div>
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
  appState.selectedAccountIds = new Set(
    appState.accounts.filter(account => account.default_selected && account.enabled).map(account => account.id)
  );
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
  let confirmLiveOrder = false;
  if (liveGateOpen()) {
    confirmLiveOrder = window.confirm(`Submit LIVE Schwab order?\\n\\n${proposal.tos_order_line}\\nAccounts: ${selectedIds.join(", ")}\\nMax loss: ${money(proposal.max_loss)}\\n\\nOnly continue if this is exactly the trade you want.`);
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
    order_note: `Schwab Market Scanner | ${proposal.symbol} ${proposal.direction || ""} | ${proposalMoneyness(proposal)}`
  };
  const opts = authOptions("POST", body);
  const result = await fetchJson(`/proposals/${encodeURIComponent(proposal.id)}/send`, opts);
  if (!result.ok) {
    if (status) status.textContent = result.data?.detail || result.data?.body || `HTTP ${result.status}`;
    return;
  }
  appState.sendResponses[proposal.id] = result.data;
  if (Array.isArray(result.data.selected_account_ids)) {
    appState.selectedAccountIds = new Set(result.data.selected_account_ids);
  }
  render();
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
</script>
</body>
</html>"""
