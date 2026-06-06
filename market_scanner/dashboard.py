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
      --muted: #64748b;
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
    }
    button.primary { background: var(--blue); border-color: var(--blue); color: white; font-weight: 700; }
    button.good { background: var(--green-bg); border-color: #bbf7d0; color: var(--green); font-weight: 800; }
    button.ghost { background: #f8fafc; }
    button:disabled { cursor: not-allowed; color: #94a3b8; background: #f8fafc; }
    input {
      border: 1px solid var(--line);
      background: white;
      border-radius: 7px;
      padding: 9px 11px;
      min-width: 230px;
    }
    .page { max-width: 1840px; margin: 0 auto; padding: 22px; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
    .title h1 { margin: 0; font-size: 23px; line-height: 1.1; letter-spacing: 0; }
    .title .sub { margin-top: 6px; color: var(--muted); font-size: 14px; }
    .top-actions { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; justify-content: flex-end; }
    .layout { display: grid; grid-template-columns: minmax(520px, 0.9fr) minmax(620px, 1.1fr); gap: 14px; align-items: start; }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 15px;
      border-bottom: 1px solid var(--line-soft);
    }
    .panel-head h2 { margin: 0; font-size: 16px; }
    .panel-body { padding: 14px 15px; }
    .kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
    .kpi { min-height: 82px; padding: 12px; background: white; border: 1px solid var(--line); border-radius: 8px; }
    .kpi .label { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .kpi .value { margin-top: 8px; font-size: 18px; font-weight: 800; overflow-wrap: anywhere; }
    .state-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding-top: 12px; border-top: 1px solid var(--line-soft); }
    .state .label { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .state .value { margin-top: 5px; font-weight: 800; }
    .badges { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 13px;
      font-weight: 800;
      background: #eef2ff;
      color: #1d4ed8;
      border: 1px solid #dbeafe;
    }
    .badge.green { background: var(--green-bg); color: var(--green); border-color: #bbf7d0; }
    .badge.amber { background: var(--amber-bg); color: var(--amber); border-color: #fed7aa; }
    .badge.red { background: var(--red-bg); color: var(--red); border-color: #fecdd3; }
    .badge.gray { background: #f8fafc; color: #475569; border-color: var(--line); }
    .notice { border-left: 4px solid var(--amber); background: #fff7ed; padding: 12px 14px; border-radius: 7px; color: #7c3f06; line-height: 1.45; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; table-layout: fixed; }
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
    .proposal-toolbar { display: grid; grid-template-columns: 1fr auto; gap: 12px; align-items: start; }
    .proposal-title h2 { margin: 0 0 5px; font-size: 16px; }
    .proposal-controls { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .candidate-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 14px 0; }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfdff; }
    .metric .label { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .metric .value { margin-top: 7px; font-size: 18px; font-weight: 900; }
    .proposal-card {
      border: 1px solid #bbf7d0;
      border-left: 6px solid var(--green);
      border-radius: 8px;
      background: var(--green-bg);
      padding: 14px;
      margin-top: 12px;
    }
    .proposal-card.sim { border-color: #fed7aa; border-left-color: var(--amber); background: #fffaf0; }
    .proposal-top { display: flex; align-items: start; justify-content: space-between; gap: 12px; }
    .proposal-name { font-weight: 900; font-size: 16px; }
    .proposal-meta { margin-top: 4px; color: var(--muted); font-size: 13px; }
    .proposal-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 9px; margin-top: 12px; }
    .order-line {
      margin-top: 10px;
      background: var(--navy);
      color: white;
      border-radius: 6px;
      padding: 12px;
      overflow-x: auto;
      white-space: pre;
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      font-size: 13px;
    }
    .proposal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
    .reasons { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 10px; }
    .note-list { margin-top: 8px; color: var(--muted); font-size: 13px; line-height: 1.45; }
    .empty { padding: 24px; color: var(--muted); text-align: center; border: 1px dashed var(--line); border-radius: 8px; background: #fbfdff; }
    @media (max-width: 1180px) {
      .layout { grid-template-columns: 1fr; }
      .right-panel { position: static; }
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
      .page { padding: 14px; }
      .topbar, .proposal-toolbar { align-items: stretch; flex-direction: column; display: flex; }
      .top-actions, .proposal-controls { justify-content: stretch; }
      .top-actions > *, .proposal-controls > * { flex: 1 1 auto; }
      input { min-width: 0; width: 100%; }
      .state-grid, .candidate-summary, .proposal-stats { grid-template-columns: 1fr; }
      .kpis { grid-template-columns: 1fr; }
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
        <input id="api-key" type="password" placeholder="API key">
        <button class="ghost" onclick="load()">Refresh</button>
        <button class="good" onclick="replayFriday()">Friday Replay</button>
        <button class="primary" onclick="runScan()">Run Scan</button>
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
          <div class="panel-body">
            <div class="state-grid">
              <div class="state"><div class="label">Scan</div><div class="value" id="state-scan">...</div></div>
              <div class="state"><div class="label">Universe</div><div class="value" id="state-universe">...</div></div>
              <div class="state"><div class="label">Session</div><div class="value" id="state-session">...</div></div>
              <div class="state"><div class="label">Safety</div><div class="value" id="state-safety">...</div></div>
            </div>
          </div>
        </section>

        <section class="panel" style="margin-top: 12px;">
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
            <button class="ghost" onclick="copySelectedTos()">Copy TOS</button>
            <button class="ghost" disabled id="send-button">Send disabled</button>
          </div>
        </div>
        <div class="panel-body">
          <div id="proposal-notice" class="notice">Loading scanner state...</div>
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
let appState = { health: null, schwab: null, scan: null, selectedSymbol: null, currentProposals: [] };

function byId(id) { return document.getElementById(id); }
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
}
function money(value) { return value === null || value === undefined ? "--" : "$" + Number(value).toFixed(2); }
function plainMoney(value) { return value === null || value === undefined ? "--" : Number(value).toFixed(2); }
function pct(value) { return value === null || value === undefined ? "--" : Number(value).toFixed(2) + "%"; }
function intFmt(value) { return value === null || value === undefined ? "0" : Number(value).toLocaleString(); }
function shortTime(value) {
  if (!value) return "No scan";
  return new Date(value).toLocaleString();
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
function apiKey() { return byId("api-key").value.trim(); }
function setStatus(text) { byId("last-update").textContent = text; }

async function fetchJson(url, opts) {
  const res = await fetch(url, opts || {});
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = { body: text }; }
  return { ok: res.ok, status: res.status, data };
}

function authOptions(method) {
  const key = apiKey();
  if (!key) {
    byId("proposal-notice").textContent = "Enter API key to run protected scans.";
    return null;
  }
  localStorage.setItem("scannerApiKey", key);
  return { method, headers: { "X-API-Key": key } };
}

async function load() {
  const savedKey = localStorage.getItem("scannerApiKey") || "";
  if (savedKey && !byId("api-key").value) byId("api-key").value = savedKey;

  const [healthResult, schwabResult, scanResult] = await Promise.all([
    fetchJson("/health"),
    fetchJson("/schwab/status"),
    fetchJson("/scan/latest"),
  ]);
  appState.health = healthResult.data;
  appState.schwab = schwabResult.data;
  appState.scan = scanResult.data && scanResult.data.scan_id ? scanResult.data : null;
  render();
}

async function runScan() {
  const opts = authOptions("POST");
  if (!opts) return;
  setStatus("Running live scan...");
  const result = await fetchJson("/scan/run", opts);
  renderProtectedResult(result);
}

async function replayFriday() {
  const opts = authOptions("POST");
  if (!opts) return;
  setStatus("Running Friday simulated replay...");
  const result = await fetchJson("/scan/replay?as_of=2026-06-05&save=true&simulate_options=true", opts);
  renderProtectedResult(result);
}

function renderProtectedResult(result) {
  if (!result.ok) {
    const detail = result.data?.detail || result.data?.message || result.data?.body || `HTTP ${result.status}`;
    byId("proposal-notice").textContent = `Request failed: ${detail}`;
    setStatus("Request failed");
    return;
  }
  appState.scan = result.data;
  render();
}

function render() {
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

  const liveGate = Boolean(config.live_gate_open);
  const hasSim = proposals.some(isSimProposal);
  byId("state-badges").innerHTML = [
    badge((config.execution_mode || "dry_run").toUpperCase(), config.execution_mode === "live" ? "red" : "gray"),
    badge(liveGate ? "LIVE GATE ON" : "LIVE GATE OFF", liveGate ? "red" : "green"),
    badge(schwab.read_only_ready ? "SCHWAB DATA READY" : "SCHWAB DATA WAITING", schwab.read_only_ready ? "green" : "amber"),
    hasSim ? badge("SIM PROPOSALS", "amber") : badge("CURRENT PROPOSALS", "green"),
  ].join("");

  byId("state-scan").textContent = scan?.scan_id || "No scan";
  byId("state-universe").textContent = (scan?.universe || config.symbols || []).join(", ") || "...";
  byId("state-session").textContent = scan?.session || "...";
  byId("state-safety").textContent = liveGate ? "Live Enabled" : "Protected";
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
  return `<tr class="candidate-row${selected}" onclick="selectCandidate('${esc(candidate.symbol)}')">
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
  render();
}

function renderProposal(candidate) {
  if (!candidate) {
    byId("proposal-subtitle").textContent = "No candidate selected.";
    byId("proposal-notice").textContent = "Run a scan or Friday replay to populate proposals.";
    byId("proposal-cards").innerHTML = `<div class="empty">No proposal selected.</div>`;
    setMetrics(null);
    return;
  }
  const metrics = candidate.metrics || {};
  const proposals = candidateProposals(candidate);
  appState.currentProposals = proposals;
  const sim = proposals.some(isSimProposal);
  byId("proposal-subtitle").textContent = `${candidate.symbol} ${candidate.action} | ${proposals.length} proposal${proposals.length === 1 ? "" : "s"}`;
  byId("proposal-notice").textContent = sim
    ? "SIM ONLY: replayed Friday underlying prices with current Schwab option-chain contract data. Order sending is blocked."
    : "Current scanner proposals remain protected by dry-run/live execution gates.";
  setMetrics(metrics);
  byId("send-button").textContent = sim ? "SIM blocked" : "Send gated";
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

function proposalCard(proposal, index) {
  const sim = isSimProposal(proposal);
  const leg = (proposal.legs || [])[0] || {};
  const heading = `${proposal.direction?.toUpperCase() || ""} ${proposal.quantity || 1} ${proposal.symbol} ${proposal.expiry || ""} ${leg.strike || ""}${leg.right ? " " + leg.right : ""}`;
  return `<article class="proposal-card ${sim ? "sim" : ""}">
    <div class="proposal-top">
      <div>
        <div class="badges">${badge(`Trade #${index + 1}`, sim ? "amber" : "green")} ${badge(proposal.structure || "proposal", "gray")} ${sim ? badge("SIM ONLY", "amber") : badge("DRY RUN", "green")}</div>
        <div class="proposal-name">${esc(heading)}</div>
        <div class="proposal-meta">score ${plainMoney(proposal.score)} | ${proposal.structure || ""} | expiry ${esc(proposal.expiry || "")}</div>
      </div>
    </div>
    <div class="proposal-stats">
      <div class="metric"><div class="label">Underlying</div><div class="value">${plainMoney(proposal.underlying_price)}</div></div>
      <div class="metric"><div class="label">Debit</div><div class="value">${money(proposal.debit)}</div></div>
      <div class="metric"><div class="label">Max Loss</div><div class="value">${money(proposal.max_loss)}</div></div>
    </div>
    <div class="reasons">${reasonBadges(proposal.reasons, sim ? "amber" : "green")}</div>
    <div class="note-list">${(proposal.notes || []).map(note => `<div>${esc(note)}</div>`).join("")}</div>
    <div class="order-line" id="tos-${index}">${esc(proposal.tos_order_line || "")}</div>
    <div class="proposal-actions">
      <button onclick="copyProposalTos(${index})">Copy TOS</button>
      <button disabled>${sim ? "Send blocked" : "Send gated"}</button>
    </div>
  </article>`;
}

async function copyText(text) {
  if (!text) return;
  await navigator.clipboard.writeText(text);
  setStatus("Copied TOS line");
}

function copyProposalTos(index) {
  const proposal = appState.currentProposals[index];
  if (proposal?.tos_order_line) copyText(proposal.tos_order_line);
}

function copySelectedTos() {
  const scan = appState.scan;
  const candidate = (scan?.top_candidates || []).find(item => item.symbol === appState.selectedSymbol);
  const first = candidateProposals(candidate)[0];
  if (first?.tos_order_line) copyText(first.tos_order_line);
}

load();
setInterval(load, 60000);
</script>
</body>
</html>"""
