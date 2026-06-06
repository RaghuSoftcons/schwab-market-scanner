from __future__ import annotations


def dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Schwab Market Scanner</title>
  <style>
    :root { color-scheme: light; font-family: Arial, sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #15181d; }
    header { padding: 16px 22px; background: #111827; color: white; display: flex; justify-content: space-between; align-items: center; }
    main { padding: 18px 22px 40px; max-width: 1280px; margin: 0 auto; }
    button { border: 1px solid #c9ced6; background: white; border-radius: 6px; padding: 8px 11px; cursor: pointer; }
    button.primary { background: #2563eb; border-color: #2563eb; color: white; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 14px 0; }
    .panel, .card { background: white; border: 1px solid #dde1e7; border-radius: 8px; padding: 14px; }
    .panel h2, .card h3 { margin: 0 0 10px; font-size: 16px; }
    table { width: 100%; border-collapse: collapse; background: white; border: 1px solid #dde1e7; }
    th, td { text-align: left; padding: 9px; border-bottom: 1px solid #eef0f3; font-size: 13px; vertical-align: top; }
    th { background: #f0f3f7; font-weight: 700; }
    .muted { color: #687385; }
    .tag { display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 12px; background: #eef2ff; color: #1d4ed8; }
    .warn { color: #a16207; }
    .bad { color: #b91c1c; }
    .good { color: #047857; }
    .proposal { border-top: 1px solid #eef0f3; margin-top: 8px; padding-top: 8px; }
    pre { white-space: pre-wrap; background: #f8fafc; padding: 8px; border-radius: 6px; font-size: 12px; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <header>
    <strong>Schwab Market Scanner</strong>
    <div><button class="primary" onclick="runScan()">Run Scan</button></div>
  </header>
  <main>
    <div class="grid">
      <section class="panel"><h2>Service</h2><div id="health" class="muted">Loading...</div></section>
      <section class="panel"><h2>Schwab</h2><div id="schwab" class="muted">Loading...</div></section>
      <section class="panel"><h2>Regime</h2><div id="regime" class="muted">No scan yet.</div></section>
    </div>
    <section class="panel">
      <h2>Top Candidates</h2>
      <div id="scan-meta" class="muted"></div>
      <div id="candidates"></div>
    </section>
  </main>
<script>
async function fetchJson(url, opts) {
  const res = await fetch(url, opts || {});
  const text = await res.text();
  try { return JSON.parse(text); } catch { return {status: res.status, body: text}; }
}
function money(v) { return v === null || v === undefined ? "" : Number(v).toFixed(2); }
function pct(v) { return v === null || v === undefined ? "" : Number(v).toFixed(2) + "%"; }
function list(items) { return (items || []).map(x => `<div>${x}</div>`).join(""); }
async function load() {
  const health = await fetchJson("/health");
  document.getElementById("health").innerHTML =
    `<div>Status: <b>${health.status}</b></div><div>Mode: ${health.config?.execution_mode}</div><div>Live gate: ${health.config?.live_gate_open}</div>`;
  const schwab = await fetchJson("/schwab/status");
  document.getElementById("schwab").innerHTML =
    `<div>Status: <b>${schwab.status}</b></div><div>Ready: ${schwab.read_only_ready}</div><div>${list(schwab.notes)}</div>`;
  const latest = await fetchJson("/scan/latest");
  renderScan(latest);
}
async function runScan() {
  document.getElementById("scan-meta").textContent = "Running scan...";
  const result = await fetchJson("/scan/run", { method: "POST" });
  renderScan(result);
}
function renderScan(scan) {
  if (!scan || !scan.scan_id) {
    document.getElementById("scan-meta").textContent = "No scan has been saved yet.";
    return;
  }
  document.getElementById("regime").innerHTML =
    `<div>Bias: <b>${scan.regime.bias}</b></div><div>Score: ${scan.regime.score}</div><div class="muted">${list(scan.regime.reasons)}</div>`;
  document.getElementById("scan-meta").textContent = `${scan.scan_id} | ${scan.session} | ${scan.scanned_at}`;
  const rows = (scan.top_candidates || []).map(c => {
    const m = c.metrics || {};
    const proposals = (c.proposals || []).map(p => `
      <div class="proposal">
        <div><span class="tag">${p.structure}</span> Score ${p.score} | Max loss $${money(p.max_loss)} | Send ${money(p.send_limit_price)}</div>
        <pre>${p.tos_order_line}</pre>
      </div>`).join("");
    return `<tr>
      <td><b>${c.symbol}</b><br><span class="tag">${c.action}</span></td>
      <td>${money(m.current_price)}</td>
      <td>${pct(m.gap_pct)}</td>
      <td>${m.premarket_volume || 0}</td>
      <td>${money(m.premarket_high)}</td>
      <td>${money(m.previous_high)}</td>
      <td>${list(c.reasons)}<span class="warn">${list(c.warnings)}</span><span class="bad">${list(c.proposal_blocked_reasons)}</span>${proposals}</td>
    </tr>`;
  }).join("");
  document.getElementById("candidates").innerHTML = `<table>
    <thead><tr><th>Symbol</th><th>Price</th><th>Gap</th><th>PM Vol</th><th>PMH</th><th>Prev High</th><th>Read</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="7" class="muted">No candidates.</td></tr>`}</tbody>
  </table>`;
}
load();
setInterval(load, 60000);
</script>
</body>
</html>"""
