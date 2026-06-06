"""Minimal local dashboard HTML for proposal review."""

from __future__ import annotations


def render_dashboard_html() -> str:
    """Return a self-contained dashboard page served by FastAPI."""

    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NT-Schwab Bridge Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #667085;
      --line: #d7dde5;
      --teal: #0f766e;
      --blue: #2563eb;
      --amber: #b45309;
      --red: #991b1b;
      --green: #166534;
      --shadow: 0 1px 2px rgba(17, 24, 39, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-width: 320px;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 "Segoe UI", Arial, sans-serif;
    }

    button {
      font: inherit;
    }

    .shell {
      width: min(1440px, 100%);
      margin: 0 auto;
      padding: 12px;
    }

    .dashboard-layout {
      display: grid;
      grid-template-columns: minmax(500px, 0.92fr) minmax(460px, 1.08fr);
      gap: 12px;
      align-items: start;
    }

    .dashboard-main {
      display: grid;
      gap: 10px;
      min-width: 0;
    }

    .dashboard-aside {
      min-width: 0;
    }

    .topbar {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 10px;
      align-items: center;
      margin-bottom: 0;
    }

    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }

    .subline {
      margin-top: 1px;
      color: var(--muted);
      font-size: 12px;
    }

    .toolbar {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
    }

    .sound-controls {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
    }

    .sound-controls form {
      display: inline-flex;
      margin: 0;
    }

    .proposal-settings {
      align-items: center;
      display: inline-flex;
      gap: 6px;
      flex-wrap: wrap;
    }

    .setting-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }

    .target-inputs {
      align-items: center;
      display: inline-flex;
      gap: 4px;
    }

    .target-input {
      border: 1px solid var(--line);
      border-radius: 6px;
      box-sizing: border-box;
      color: var(--ink);
      font-size: 12px;
      font-weight: 800;
      height: 32px;
      padding: 4px;
      width: 44px;
    }

    .checkbox-setting {
      align-items: center;
      color: var(--ink);
      display: inline-flex;
      font-size: 12px;
      font-weight: 800;
      gap: 4px;
      min-height: 32px;
    }

    .checkbox-setting input {
      accent-color: var(--green);
      height: 16px;
      width: 16px;
    }

    .segmented {
      border: 1px solid var(--line);
      border-radius: 6px;
      display: inline-grid;
      grid-auto-columns: minmax(44px, auto);
      grid-auto-flow: column;
      overflow: hidden;
    }

    .segment-button {
      background: var(--panel);
      border: 0;
      border-right: 1px solid var(--line);
      color: var(--ink);
      cursor: pointer;
      min-height: 32px;
      padding: 6px 8px;
    }

    .segment-button:last-child {
      border-right: 0;
    }

    .segment-button.active {
      background: #e8f5ee;
      color: var(--green);
      font-weight: 700;
    }

    .segment-button:disabled {
      color: var(--muted);
      cursor: not-allowed;
      opacity: 0.7;
    }

    .button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      min-height: 34px;
      padding: 7px 11px;
      border-radius: 6px;
      cursor: pointer;
      box-shadow: var(--shadow);
    }

    .button:disabled {
      color: var(--muted);
      cursor: not-allowed;
      opacity: 0.65;
    }

    .button.danger {
      color: var(--red);
      font-weight: 700;
    }

    .button.sound-ready {
      border-color: #b7dfc5;
      background: #e8f5ee;
      color: var(--green);
      font-weight: 700;
    }

    .button.sound-off {
      color: var(--muted);
    }

    .sound-status {
      color: var(--muted);
      font-size: 12px;
      min-width: 72px;
    }

    .sound-status.ok {
      color: var(--green);
      font-weight: 700;
    }

    .sound-status.error {
      color: var(--red);
      font-weight: 700;
    }

    .button:focus-visible,
    .segment-button:focus-visible,
    .signal-row:focus-visible {
      outline: 2px solid var(--blue);
      outline-offset: 2px;
    }

    .status-line {
      min-height: 20px;
      color: var(--muted);
      font-size: 13px;
    }

    .state-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      padding: 10px 12px 11px;
      border-top: 1px solid var(--line);
    }

    .state-value {
      margin-top: 2px;
      font-size: 15px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .state-value.green {
      color: var(--green);
    }

    .state-value.amber {
      color: var(--amber);
    }

    .state-value.red {
      color: var(--red);
    }

    .state-value.blue {
      color: var(--blue);
    }

    .chain-check {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      padding: 10px 12px;
      border-top: 1px solid var(--line);
      background: #fbfcfe;
    }

    .chain-check-output {
      color: var(--muted);
      overflow-wrap: anywhere;
    }

    .chain-check-note {
      color: var(--ink);
      font-weight: 700;
      margin-bottom: 8px;
    }

    .chain-check-note span {
      color: var(--muted);
      font-weight: 500;
    }

    .chain-check-facts {
      display: grid;
      grid-template-columns: repeat(4, minmax(130px, 1fr));
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #ffffff;
      padding: 6px 8px;
    }

    .chain-check-fact strong {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      margin-bottom: 3px;
      text-transform: uppercase;
    }

    .chain-check-fact span {
      color: var(--ink);
      display: block;
      font-size: 13px;
      font-weight: 700;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr);
      gap: 12px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .panel-head {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
    }

    .panel-title {
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }

    .panel-body {
      padding: 12px;
    }

    .dashboard-aside .panel-head {
      align-items: flex-start;
    }

    .dashboard-aside .toolbar {
      flex: 1;
    }

    .metrics {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 0;
    }

    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 7px 8px;
      min-height: 54px;
      background: #fbfcfe;
    }

    .label {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .value {
      margin-top: 2px;
      font-size: 16px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .badges {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 700;
      border: 1px solid var(--line);
      background: #eef2f7;
      color: var(--ink);
      white-space: nowrap;
    }

    .badge.green {
      background: #e8f5ee;
      color: var(--green);
      border-color: #b7dfc5;
    }

    .badge.amber {
      background: #fff4df;
      color: var(--amber);
      border-color: #f0d39a;
    }

    .badge.red {
      background: #feecec;
      color: var(--red);
      border-color: #f2bcbc;
    }

    .badge.blue {
      background: #eaf1ff;
      color: var(--blue);
      border-color: #bfd2ff;
    }

    .table-wrap {
      overflow-x: auto;
      width: 100%;
    }

    .signals-table {
      width: 100%;
      min-width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }

    .signals-table th,
    .signals-table td {
      padding: 8px 8px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: middle;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .signals-table th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }

    .signals-table .badge {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .signal-row {
      cursor: pointer;
    }

    .signal-row:hover,
    .signal-row.selected {
      background: #f0f7f6;
    }

    .signal-row.has-proposal {
      background: #f4fbf7;
    }

    .signal-row.has-proposal.selected {
      background: #e7f6ee;
      box-shadow: inset 4px 0 0 var(--green);
    }

    .empty {
      color: var(--muted);
      min-height: 60px;
      display: grid;
      place-items: center;
      text-align: center;
      padding: 18px;
    }

    .proposal-list {
      display: grid;
      gap: 10px;
    }

    .candidate-diagnostics {
      display: grid;
      gap: 8px;
      margin: 10px 0;
    }

    .candidate {
      border: 1px solid #f0d39a;
      border-radius: 8px;
      padding: 9px;
      background: #fffaf0;
    }

    .candidate-title {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .candidate-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }

    .candidate-reasons {
      color: #6f4200;
      font-size: 12px;
      margin-top: 6px;
      overflow-wrap: anywhere;
    }

    .freshness {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 10px 0;
    }

    .freshness-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #fbfcfe;
    }

    .freshness-value {
      margin-top: 2px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .proposal {
      border: 2px solid #15803d;
      border-radius: 8px;
      border-left-width: 7px;
      padding: 10px 11px;
      background: #f0fdf4;
      box-shadow: 0 1px 2px rgba(21, 128, 61, 0.12);
    }

    .proposal-main {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: start;
      margin-bottom: 8px;
    }

    .proposal-title {
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .trade-number {
      align-items: center;
      background: #14532d;
      border-radius: 6px;
      color: #ffffff;
      display: inline-flex;
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 5px;
      min-height: 24px;
      padding: 2px 8px;
    }

    .proposal-meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }

    .proposal-guide {
      border: 1px solid #b7dfc5;
      border-left: 4px solid var(--green);
      border-radius: 8px;
      background: #f0fbf5;
      padding: 10px 12px;
      margin-bottom: 10px;
      color: #0b5c2f;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .proposal-facts {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 6px;
    }

    .proposal-fact {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 6px 8px;
      background: #ffffff;
      min-width: 0;
    }

    .proposal-fact-value {
      margin-top: 2px;
      font-size: 15px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .proposal-quantity-control {
      align-items: center;
      display: inline-flex;
      gap: 6px;
      margin-top: 6px;
    }

    .proposal-qty-segmented {
      grid-auto-columns: 34px;
    }

    .proposal-quantity-button[disabled] {
      cursor: not-allowed;
      opacity: 0.45;
    }

    .legs {
      display: grid;
      gap: 4px;
      margin-top: 6px;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
    }

    .tos-line {
      border: 0;
      box-sizing: border-box;
      display: block;
      margin-top: 8px;
      padding: 12px;
      border-radius: 6px;
      background: #111827;
      color: #f9fafb;
      font-family: Consolas, "Courier New", monospace;
      font-size: 14px;
      font-weight: 700;
      overflow-x: auto;
      resize: none;
      white-space: pre;
      width: 100%;
    }

    .order-note {
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
      overflow-wrap: anywhere;
    }

    .exit-plan {
      border-top: 1px solid var(--line);
      color: var(--muted);
      display: grid;
      gap: 4px;
      font-size: 12px;
      margin-top: 8px;
      padding-top: 8px;
    }

    .exit-targets {
      display: grid;
      gap: 6px;
    }

    .exit-target {
      color: var(--ink);
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .exit-order-row {
      align-items: stretch;
      display: flex;
      gap: 8px;
      margin-top: 3px;
    }

    .exit-order-line {
      background: #e5e7eb;
      border-radius: 6px;
      color: #111827;
      display: block;
      flex: 1 1 auto;
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      font-weight: 700;
      margin-top: 0;
      padding: 6px 8px;
      white-space: normal;
    }

    .exit-plan-note {
      color: var(--amber);
      font-size: 12px;
    }

    .tos-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: 8px;
    }

    .tos-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      justify-content: flex-end;
    }

    .copy-button {
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--blue);
      min-height: 28px;
      padding: 4px 8px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }

    .copy-button.copied {
      color: var(--green);
      border-color: #b7dfc5;
      background: #e8f5ee;
    }

    .copy-exit-tos-button {
      flex: 0 0 auto;
      white-space: nowrap;
    }

    .send-button {
      color: var(--green);
    }

    .send-button.blocked {
      color: var(--amber);
      border-color: #f0cf9a;
      background: #fff8ea;
    }

    .send-button.sent {
      color: var(--green);
      border-color: #b7dfc5;
      background: #e8f5ee;
    }

    .exit-send-confirmation {
      color: var(--amber);
      display: block;
      font-size: 12px;
      font-weight: 700;
      margin-top: 4px;
    }

    .exit-send-confirmation.submitted {
      color: var(--green);
    }

    .account-routing {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
      display: grid;
      gap: 6px;
      margin-top: 8px;
      padding: 8px;
    }

    .account-route {
      align-items: center;
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 8px;
      min-width: 0;
      border-radius: 6px;
      padding: 4px 5px;
    }

    .account-route input {
      width: 16px;
      height: 16px;
    }

    .account-route-label {
      color: var(--ink);
      font-weight: 700;
      overflow-wrap: anywhere;
    }

    .account-route-meta {
      color: var(--muted);
      font-size: 12px;
    }

    .account-route.blocked {
      opacity: 0.62;
    }

    .account-route.balance-ok {
      background: #eefaf2;
      border: 1px solid #b7dfc5;
    }

    .account-route.balance-low {
      background: #fff1f1;
      border: 1px solid #f2bcbc;
    }

    .account-route-actions {
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: flex-end;
    }

    .account-balance {
      border: 1px solid var(--line);
      border-radius: 999px;
      display: inline-flex;
      font-size: 11px;
      font-weight: 800;
      min-height: 24px;
      padding: 3px 8px;
      white-space: nowrap;
    }

    .account-balance.green {
      background: #dff4e7;
      border-color: #9bd2ad;
      color: var(--green);
    }

    .account-balance.red {
      background: #fee2e2;
      border-color: #e6a3a3;
      color: var(--red);
    }

    .account-balance.neutral {
      background: #eef2f7;
      color: var(--muted);
    }

    .send-status {
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
      min-height: 18px;
      overflow-wrap: anywhere;
    }

    .leg {
      padding: 5px 6px;
      border-radius: 6px;
      background: #eef2f7;
      overflow-wrap: anywhere;
    }

    .split {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }

    .notice {
      border-left: 4px solid var(--amber);
      background: #fff8ea;
      padding: 10px 12px;
      color: #6f4200;
      border-radius: 6px;
      overflow-wrap: anywhere;
    }

    @media (max-width: 1100px) {
      .dashboard-layout,
      .topbar,
      .grid,
      .metrics,
      .split,
      .state-grid,
      .chain-check {
        grid-template-columns: 1fr;
      }

      .chain-check-facts {
        grid-template-columns: 1fr;
      }

      .toolbar {
        justify-content: flex-start;
      }
    }

    @media (max-width: 600px) {
      .shell {
        padding: 12px;
      }

      h1 {
        font-size: 17px;
      }

      .signals-table th,
      .signals-table td {
        padding: 8px 6px;
      }

      .signals-table {
        min-width: 720px;
      }

      .proposal-facts {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <div class="dashboard-layout">
      <div class="dashboard-main">
        <header class="topbar">
          <div>
            <h1>NT-Schwab Bridge Dashboard</h1>
            <div class="subline" id="last-update">Waiting for bridge status</div>
          </div>
          <div class="toolbar">
            <button class="button" id="demo-signal-button" type="button" style="display: none;">Demo Signal</button>
            <button class="button" id="refresh-button" type="button">Refresh</button>
          </div>
        </header>

        <section class="metrics" aria-label="Bridge status">
          <div class="metric">
            <div class="label">Bridge</div>
            <div class="value" id="metric-bridge">--</div>
          </div>
          <div class="metric">
            <div class="label">Signals</div>
            <div class="value" id="metric-signals">--</div>
          </div>
          <div class="metric">
            <div class="label">Latest Proposal</div>
            <div class="value" id="metric-proposals">--</div>
          </div>
          <div class="metric">
            <div class="label">Execution Lock</div>
            <div class="value" id="metric-lock">--</div>
          </div>
          <div class="metric">
            <div class="label">Schwab Data</div>
            <div class="value" id="metric-data">--</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Operating State</div>
            <div class="badges" id="state-badges"></div>
          </div>
          <div class="state-grid" aria-label="Current operating state">
            <div>
              <div class="label">Run State</div>
              <div class="state-value" id="state-run">--</div>
            </div>
            <div>
              <div class="label">Review Queue</div>
              <div class="state-value" id="state-review">--</div>
            </div>
            <div>
              <div class="label">Data Path</div>
              <div class="state-value" id="state-data-path">--</div>
            </div>
            <div>
              <div class="label">Safety</div>
              <div class="state-value" id="state-safety">--</div>
            </div>
          </div>
          <div class="chain-check">
            <div>
              <div class="label">Schwab Chain Check</div>
              <div class="chain-check-output" id="schwab-chain-check-output">Ready for a manual read-only SPY check</div>
            </div>
            <button class="button" id="schwab-chain-check-button" type="button">Check Schwab Chain</button>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Recent Signals</div>
            <div class="toolbar">
              <div class="status-line" id="signals-status"></div>
              <button class="button danger" id="clear-signals-button" type="button">Clear Signals</button>
            </div>
          </div>
          <div class="table-wrap">
            <table class="signals-table">
              <thead>
                <tr>
                  <th style="width: 23%;">Received</th>
                  <th style="width: 9%;">Symbol</th>
                  <th style="width: 8%;">Side</th>
                  <th style="width: 17%;">Source</th>
                  <th style="width: 18%;">Decision</th>
                  <th style="width: 11%;">Proposals</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody id="signals-body"></tbody>
            </table>
          </div>
        </section>
      </div>

      <aside class="dashboard-aside">
        <section class="panel">
          <div class="panel-head">
            <div class="panel-title">Current Proposal</div>
            <div class="toolbar">
              <div class="status-line" id="proposal-status"></div>
              <span class="proposal-settings" aria-label="Expiry settings">
                <span class="setting-label">Expiry</span>
                <span class="segmented" id="expiry-buttons" role="group" aria-label="Proposal expiry"></span>
              </span>
              <span class="proposal-settings" aria-label="Moneyness settings">
                <label class="checkbox-setting"><input id="allow-itm-checkbox" type="checkbox">ITM</label>
              </span>
              <span class="proposal-settings" aria-label="Proposal settings">
                <span class="setting-label">Max Loss</span>
                <span class="segmented" id="max-loss-buttons" role="group" aria-label="Proposal max loss"></span>
              </span>
              <span class="proposal-settings" aria-label="Entry offset settings">
                <span class="setting-label">Entry +</span>
                <span class="segmented" id="entry-offset-buttons" role="group" aria-label="Proposal entry offset"></span>
              </span>
              <span class="proposal-settings" aria-label="Target settings">
                <span class="setting-label">Targets</span>
                <span class="target-inputs" id="target-percent-controls" role="group" aria-label="Proposal targets"></span>
              </span>
              <span class="sound-controls">
                <button class="button sound-ready" id="sound-toggle-button" type="button">Sound Ready</button>
                <form action="/dashboard/sound/test" id="sound-test-form" method="post" target="sound-test-frame">
                  <button class="button" id="sound-test-button" type="button">Test Sound</button>
                </form>
                <iframe name="sound-test-frame" title="Sound test result" style="border: 0; height: 0; left: -9999px; position: absolute; width: 0;"></iframe>
                <span class="sound-status" id="sound-status" aria-live="polite"></span>
              </span>
              <button class="button" id="show-proposal-button" type="button" disabled>Show Proposal</button>
              <button class="button" id="mark-reviewed-button" type="button" disabled>Mark Reviewed</button>
              <button class="button" id="proposal-refresh-button" type="button" disabled>Refresh Proposal</button>
            </div>
          </div>
          <div class="panel-body">
            <div id="proposal-guide" class="proposal-guide" style="display: none;"></div>
            <div id="proposal-notice" class="notice" style="display: none;"></div>
            <div id="schwab-status-notice" class="notice" style="display: none; margin-top: 10px;"></div>
            <div id="quote-freshness" class="freshness"></div>
            <div id="candidate-diagnostics" class="candidate-diagnostics"></div>
            <div id="proposal-list" class="proposal-list"></div>
          </div>
        </section>
      </aside>
    </div>
  </main>

  <script>
    let selectedSignalId = null;
    let userSelectedSignal = false;
    let bestProposalSignalId = null;
    let signalById = new Map();
    let currentConfig = {};
    let currentSchwabStatus = {};
    let currentProposalResult = null;
    let proposalOrderStatuses = new Map();
    let entrySendResponses = new Map();
    let exitSendResponses = new Map();
    let proposalQuantityOverrides = new Map();
    let targetDraftValues = null;
    let dashboardRefreshTimer = null;
    const MAX_PROPOSAL_QUANTITY = 10;
    const OPTIONS_REFRESH_ACTIVE_MS = 5000;
    const OPTIONS_REFRESH_IDLE_MS = 60000;
    const OPTIONS_REFRESH_TIME_ZONE = "America/New_York";
    let dashboardSettings = {
      allow_itm: false,
      max_loss_dollars: 300,
      max_loss_choices: [200, 300, 400, 500],
      entry_offset_cents: 30,
      entry_offset_choices: [10, 20, 30, 40, 50],
      expiry_label: "1DTE",
      expiry_choices: ["0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY"],
      target_percentages: [20, 40, 50]
    };
    let schwabAccounts = [];
    let schwabAccountNotes = [];
    let selectedAccountIds = new Set();
    let proposalAlertCounts = new Map();
    let proposalAlertsPrimed = false;
    let proposalSoundContext = null;
    let proposalAudioElement = null;
    let proposalAudioDataUrl = null;
    let pendingProposalSound = false;
    let lastProposalAlertAt = 0;
    let soundStatusTimer = null;
    let lastLocalSoundStarted = false;
    let lastLocalSoundMethod = "";
    let soundUserEnabled = true;
    let activeSpeechUtterance = null;
    let speechVoicesPromise = null;
    let lastSpeechAlertStarted = false;
    let lastSpeechAlertError = "";
    let speechStartTimeout = null;

    const fmtTime = (value) => {
      if (!value) return "--";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString();
    };

    const fmtMoney = (value) => {
      const amount = Number(value);
      if (!Number.isFinite(amount)) return "--";
      return amount.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      });
    };

    const text = (id, value) => {
      document.getElementById(id).textContent = value == null || value === "" ? "--" : String(value);
    };

    const escapeHtml = (value) => String(value == null || value === "" ? "--" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));

    const badge = (label, tone) => `<span class="badge ${tone || ""}">${escapeHtml(label)}</span>`;

    function proposalSoundAllowed() {
      return Boolean(soundUserEnabled && currentConfig.dashboard_alerts_enabled && currentConfig.dashboard_sound_enabled);
    }

    function ensureProposalSoundContext() {
      if (!proposalSoundAllowed()) return null;
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return null;
      if (!proposalSoundContext) {
        proposalSoundContext = new AudioContextClass();
      }
      return proposalSoundContext;
    }

    function setSoundStatus(message, tone) {
      const status = document.getElementById("sound-status");
      if (!status) return;
      if (soundStatusTimer) {
        window.clearTimeout(soundStatusTimer);
        soundStatusTimer = null;
      }
      status.textContent = message || "";
      status.className = `sound-status ${tone || ""}`.trim();
      if (message && tone !== "error") {
        soundStatusTimer = window.setTimeout(() => {
          status.textContent = "";
          status.className = "sound-status";
        }, 3500);
      }
    }

    function updateSoundControls() {
      const toggle = document.getElementById("sound-toggle-button");
      const test = document.getElementById("sound-test-button");
      if (!toggle || !test) return;
      const configAllows = Boolean(currentConfig.dashboard_alerts_enabled && currentConfig.dashboard_sound_enabled);
      test.disabled = !configAllows;
      if (!configAllows) {
        toggle.textContent = "Sound Off";
        toggle.disabled = true;
        toggle.className = "button sound-off";
        setSoundStatus("Disabled", "error");
        return;
      }
      const status = document.getElementById("sound-status");
      if (status && status.textContent === "Disabled") {
        setSoundStatus("", "");
      }
      toggle.disabled = false;
      if (!soundUserEnabled) {
        toggle.textContent = "Sound Off";
        toggle.className = "button sound-off";
        return;
      }
      toggle.textContent = "Sound Ready";
      toggle.className = "button sound-ready";
    }

    function bytesToBase64(bytes) {
      let binary = "";
      const chunkSize = 32768;
      for (let offset = 0; offset < bytes.length; offset += chunkSize) {
        const chunk = bytes.subarray(offset, offset + chunkSize);
        binary += String.fromCharCode(...chunk);
      }
      return btoa(binary);
    }

    function createProposalAlertDataUrl() {
      const sampleRate = 44100;
      const durationSeconds = 1.1;
      const sampleCount = Math.floor(sampleRate * durationSeconds);
      const dataLength = sampleCount * 2;
      const buffer = new ArrayBuffer(44 + dataLength);
      const view = new DataView(buffer);
      const writeText = (offset, value) => {
        for (let index = 0; index < value.length; index += 1) {
          view.setUint8(offset + index, value.charCodeAt(index));
        }
      };
      writeText(0, "RIFF");
      view.setUint32(4, 36 + dataLength, true);
      writeText(8, "WAVE");
      writeText(12, "fmt ");
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeText(36, "data");
      view.setUint32(40, dataLength, true);
      const tones = [
        { start: 0.0, end: 0.24, frequency: 740 },
        { start: 0.31, end: 0.55, frequency: 988 },
        { start: 0.62, end: 1.02, frequency: 1244 }
      ];
      for (let index = 0; index < sampleCount; index += 1) {
        const time = index / sampleRate;
        const tone = tones.find((item) => time >= item.start && time <= item.end);
        let value = 0;
        if (tone) {
          const localTime = time - tone.start;
          const toneDuration = tone.end - tone.start;
          const attack = Math.min(1, localTime / 0.02);
          const release = Math.min(1, (toneDuration - localTime) / 0.05);
          const envelope = Math.max(0, Math.min(attack, release));
          const angle = 2 * Math.PI * tone.frequency * time;
          const fundamental = Math.sin(angle);
          const harmonic = 0.35 * Math.sin(angle * 2);
          value = 0.9 * envelope * ((fundamental + harmonic) / 1.35);
        }
        const clamped = Math.max(-1, Math.min(1, value));
        view.setInt16(44 + index * 2, Math.round(clamped * 32767), true);
      }
      return `data:audio/wav;base64,${bytesToBase64(new Uint8Array(buffer))}`;
    }

    function ensureProposalAudioElement() {
      if (!proposalSoundAllowed()) return null;
      if (!proposalAudioDataUrl) {
        proposalAudioDataUrl = createProposalAlertDataUrl();
      }
      if (!proposalAudioElement) {
        proposalAudioElement = new Audio(proposalAudioDataUrl);
        proposalAudioElement.preload = "auto";
        proposalAudioElement.volume = 1.0;
      }
      return proposalAudioElement;
    }

    async function playLocalBridgeSound(force) {
      lastLocalSoundStarted = false;
      lastLocalSoundMethod = "";
      try {
        const result = await postJson(force ? "/dashboard/sound/test" : "/dashboard/sound/alert", {});
        lastLocalSoundStarted = result.status === "started";
        lastLocalSoundMethod = result.method || "local";
        return lastLocalSoundStarted;
      } catch (error) {
        return false;
      }
    }

    async function playAudioElementSound() {
      const audio = ensureProposalAudioElement();
      if (!audio) return false;
      try {
        audio.pause();
        audio.currentTime = 0;
        audio.volume = 1.0;
        const playResult = audio.play();
        if (playResult && typeof playResult.then === "function") {
          await playResult;
        }
        return true;
      } catch (error) {
        return false;
      }
    }

    function speechSupported() {
      return Boolean("speechSynthesis" in window && window.SpeechSynthesisUtterance);
    }

    function getSpeechVoices() {
      if (!speechSupported()) return [];
      try {
        return window.speechSynthesis.getVoices() || [];
      } catch (error) {
        return [];
      }
    }

    function chooseSpeechVoice(voices) {
      if (!voices || !voices.length) return null;
      const preferredNames = ["Microsoft Zira", "Microsoft David", "Google US English"];
      for (const preferred of preferredNames) {
        const match = voices.find((voice) => voice.name && voice.name.includes(preferred));
        if (match) return match;
      }
      return voices.find((voice) => /^en[-_]/i.test(voice.lang || "")) || voices[0];
    }

    function warmSpeechVoices() {
      if (!speechSupported()) return Promise.resolve([]);
      const loaded = getSpeechVoices();
      if (loaded.length) return Promise.resolve(loaded);
      if (speechVoicesPromise) return speechVoicesPromise;
      speechVoicesPromise = new Promise((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          window.speechSynthesis.removeEventListener("voiceschanged", finish);
          resolve(getSpeechVoices());
        };
        window.speechSynthesis.addEventListener("voiceschanged", finish);
        window.setTimeout(finish, 900);
      });
      return speechVoicesPromise;
    }

    function playSpeechAlert(force, updateStatus) {
      lastSpeechAlertStarted = false;
      lastSpeechAlertError = "";
      if (!proposalSoundAllowed() || !speechSupported()) {
        lastSpeechAlertError = "browser speech unavailable";
        return false;
      }
      try {
        if (speechStartTimeout) window.clearTimeout(speechStartTimeout);
        const voices = getSpeechVoices();
        if (!voices.length) warmSpeechVoices();
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance("New Proposal");
        const selectedVoice = chooseSpeechVoice(voices);
        if (selectedVoice) utterance.voice = selectedVoice;
        utterance.volume = 1.0;
        utterance.rate = 0.95;
        utterance.pitch = 1.0;
        utterance.onstart = () => {
          lastSpeechAlertStarted = true;
          lastSpeechAlertError = "";
          if (speechStartTimeout) window.clearTimeout(speechStartTimeout);
          if (updateStatus) setSoundStatus("New Proposal played", "ok");
        };
        utterance.onend = () => {
          if (activeSpeechUtterance === utterance) activeSpeechUtterance = null;
        };
        utterance.onerror = (event) => {
          if (activeSpeechUtterance === utterance) activeSpeechUtterance = null;
          lastSpeechAlertError = event && event.error ? `speech error: ${event.error}` : "speech error";
          if (speechStartTimeout) window.clearTimeout(speechStartTimeout);
          if (updateStatus) setSoundStatus(`Beep played; ${lastSpeechAlertError}`, "error");
        };
        activeSpeechUtterance = utterance;
        window.speechSynthesis.speak(utterance);
        if (typeof window.speechSynthesis.resume === "function") {
          window.speechSynthesis.resume();
        }
        if (updateStatus) {
          speechStartTimeout = window.setTimeout(() => {
            if (!lastSpeechAlertStarted) {
              lastSpeechAlertError = "speech did not start";
              setSoundStatus("Beep played; speech did not start", "error");
            }
          }, 2200);
        }
        return true;
      } catch (error) {
        lastSpeechAlertError = error && error.message ? error.message : "speech failed";
        return false;
      }
    }

    function playTone(context, frequency, start, duration, peakGain) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "triangle";
      oscillator.frequency.setValueAtTime(frequency, start);
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.linearRampToValueAtTime(peakGain || 0.42, start + 0.025);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(start);
      oscillator.stop(start + duration + 0.04);
    }

    function playBrowserProposalChime(context, force) {
      const start = context.currentTime + 0.02;
      const mainGain = force ? 0.72 : 0.5;
      const harmonicGain = force ? 0.24 : 0.16;
      playTone(context, 880, start, 0.36, mainGain);
      playTone(context, 1320, start, 0.3, harmonicGain);
    }

    async function playBrowserProposalSound(force) {
      if (!proposalSoundAllowed()) return false;
      const speechStarted = playSpeechAlert(force, false);
      let audioElementPlayed = false;
      let webAudioPlayed = false;
      const context = ensureProposalSoundContext();
      if (context && context.state === "suspended") {
        try {
          await context.resume();
        } catch (error) {
          updateSoundControls();
        }
      }
      if (context && context.state === "running") {
        try {
          playBrowserProposalChime(context, force);
          webAudioPlayed = true;
        } catch (error) {
          webAudioPlayed = false;
        }
      }
      if (!webAudioPlayed) {
        audioElementPlayed = await playAudioElementSound();
      }
      return audioElementPlayed || webAudioPlayed || speechStarted;
    }

    function claimProposalAlertPlayback(nowMs) {
      try {
        const key = "nt_schwab_proposal_alert_started_at";
        const previous = Number(window.localStorage.getItem(key) || 0);
        if (previous && nowMs - previous < 1800) {
          return false;
        }
        window.localStorage.setItem(key, String(nowMs));
        return true;
      } catch (error) {
        return true;
      }
    }

    async function playProposalSound(force) {
      if (!proposalSoundAllowed()) return false;
      const nowMs = Date.now();
      if (!force && nowMs - lastProposalAlertAt < 1500) return false;
      if (!force && !claimProposalAlertPlayback(nowMs)) return false;
      if (force) {
        const speechRequested = playSpeechAlert(true, true);
        const localBridgePlayed = await playLocalBridgeSound(true);
        if (speechRequested || localBridgePlayed) {
          lastProposalAlertAt = nowMs;
          pendingProposalSound = false;
          return speechRequested;
        }
        const browserPlayed = await playBrowserProposalSound(true);
        if (browserPlayed) {
          lastProposalAlertAt = nowMs;
          pendingProposalSound = false;
          return true;
        }
        pendingProposalSound = true;
        setSoundStatus("Sound failed", "error");
        return false;
      }
      const localBridgePlayed = await playLocalBridgeSound(force);
      if (localBridgePlayed) {
        lastProposalAlertAt = nowMs;
        pendingProposalSound = false;
        return true;
      }
      const speechStarted = playSpeechAlert(force, false);
      let audioElementPlayed = false;
      let webAudioPlayed = false;
      const context = ensureProposalSoundContext();
      if (!context || context.state !== "running") {
        pendingProposalSound = true;
        if (context && context.state === "suspended") {
          context.resume().then(updateSoundControls).catch(() => {});
        }
        updateSoundControls();
        if (audioElementPlayed || speechStarted) {
          pendingProposalSound = false;
          lastProposalAlertAt = nowMs;
        }
        return audioElementPlayed || speechStarted;
      }
      if (!speechStarted) {
        const start = context.currentTime + 0.02;
        try {
          playTone(context, 880, start, 0.32, force ? 0.55 : 0.42);
          webAudioPlayed = true;
        } catch (error) {
          webAudioPlayed = false;
        }
        if (!webAudioPlayed) {
          audioElementPlayed = await playAudioElementSound();
        }
      }
      const played = audioElementPlayed || webAudioPlayed || speechStarted;
      if (played) {
        lastProposalAlertAt = nowMs;
        pendingProposalSound = false;
      } else {
        pendingProposalSound = true;
        setSoundStatus("Sound failed", "error");
      }
      return played;
    }

    async function unlockProposalSound(playTest) {
      const context = ensureProposalSoundContext();
      if (!context) {
        if (playTest) {
          const played = await playProposalSound(true);
          const message = played ? "New Proposal played" : "No browser audio";
          setSoundStatus(message, played ? "ok" : "error");
          return played;
        }
        updateSoundControls();
        return false;
      }
      if (context.state === "suspended") {
        try {
          await context.resume();
        } catch (error) {
          if (playTest) setSoundStatus("Audio blocked", "error");
          updateSoundControls();
          return false;
        }
      }
      updateSoundControls();
      if (playTest && context.state === "running") {
        const played = await playProposalSound(true);
        const message = played ? "New Proposal played" : "Audio blocked";
        setSoundStatus(message, played ? "ok" : "error");
        return played;
      }
      if (pendingProposalSound && context.state === "running") {
        return await playProposalSound(true);
      }
      return false;
    }

    async function toggleProposalSound() {
      const configAllows = Boolean(currentConfig.dashboard_alerts_enabled && currentConfig.dashboard_sound_enabled);
      if (!configAllows) {
        updateSoundControls();
        return;
      }
      if (soundUserEnabled && proposalSoundContext && proposalSoundContext.state === "running") {
        soundUserEnabled = false;
        pendingProposalSound = false;
        updateSoundControls();
        return;
      }
      soundUserEnabled = true;
      await unlockProposalSound(true);
    }

    async function testProposalSound(event) {
      if (event) event.preventDefault();
      soundUserEnabled = true;
      setSoundStatus("Sound requested", "ok");
      updateSoundControls();
      const played = await playProposalSound(true);
      if (!lastSpeechAlertStarted) {
        let message = "Voice requested";
        let tone = "ok";
        if (!played && lastLocalSoundStarted) {
          message = `Beep played; ${lastSpeechAlertError || "browser voice blocked"}`;
          tone = "error";
        } else if (!played) {
          message = lastSpeechAlertError || "Audio blocked";
          tone = "error";
        } else if (lastLocalSoundStarted) {
          message = "Beep played; waiting for voice";
        }
        setSoundStatus(message, tone);
      }
    }

    function updateProposalAlertState(signals) {
      let shouldAlert = false;
      signals.forEach((record) => {
        const proposalCount = Number(record.proposal_count || 0);
        const previousCount = proposalAlertCounts.has(record.id)
          ? Number(proposalAlertCounts.get(record.id) || 0)
          : 0;
        if (proposalAlertsPrimed && proposalCount > 0 && proposalCount > previousCount) {
          shouldAlert = true;
        }
        proposalAlertCounts.set(record.id, Math.max(previousCount, proposalCount));
      });
      if (!proposalAlertsPrimed) {
        proposalAlertsPrimed = true;
        return;
      }
      if (shouldAlert) {
        playProposalSound();
      }
    }

    const decisionTone = (status) => {
      if (status === "blocked") return "red";
      if (status === "review_required") return "amber";
      if (status === "ready") return "green";
      return "blue";
    };

    const sourceBadge = (source) => {
      const label = source || "unknown";
      return badge(label === "Demo Chain" ? "DEMO" : label, label === "Demo Chain" ? "amber" : "blue");
    };

    function schwabDataStatus(config, status) {
      const state = status && status.status ? status.status : "";
      if (state === "disabled" || !config.schwab_market_data_enabled) {
        return { label: "OFF", badge: "SCHWAB DATA OFF", tone: "blue" };
      }
      if (state === "config_error") {
        return { label: "ERROR", badge: "SCHWAB CONFIG ERROR", tone: "red" };
      }
      if (state === "auth_ready") {
        return { label: "READY", badge: "SCHWAB DATA READY", tone: "green" };
      }
      if (state === "refresh_ready" || (status.read_only_ready && status.needs_refresh)) {
        return { label: "REFRESH", badge: "SCHWAB REFRESH READY", tone: "amber" };
      }
      if (state === "not_configured") {
        return { label: "NOT SET", badge: "SCHWAB DATA NOT SET", tone: "amber" };
      }
      return { label: "AUTH NEEDED", badge: "SCHWAB AUTH NEEDED", tone: "amber" };
    }

    function friendlyReason(reason) {
      if (!reason) return "--";
      if (reason === "proposals_not_generated") {
        return "No chain data has been generated for this signal yet";
      }
      if (reason === "proposal_provider_not_configured") {
        return "No option-chain provider is configured";
      }
      if (reason === "no_signal_selected") {
        return "Select a signal to inspect proposal status";
      }
      if (reason === "no_proposals_after_filters") {
        return "No contracts passed the planner filters";
      }
      if (reason === "previous_successful_proposal_preserved") {
        return "Showing previous successful proposal";
      }
      if (reason.startsWith("regular_options_session_closed:")) {
        const detail = reason.split(":").slice(1).join(":") || "09:30-16:15 Eastern";
        return `Regular options session is closed (${detail})`;
      }
      if (reason.startsWith("proposal_generation_error:")) {
        return `Provider error: ${reason.split(":").slice(1).join(":") || "unknown"}`;
      }
      if (reason.startsWith("symbol_not_enabled:")) {
        return `${reason.split(":")[1] || "Symbol"} is outside the options planner scope`;
      }
      if (reason.startsWith("no_contracts_for_expiry:")) {
        return `No contracts returned for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("no_eligible_long_contracts:")) {
        return `Contracts returned, but none passed filters for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("invalid_bid_ask:")) {
        return `Contracts had unusable bid/ask data for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("stale_quote:")) {
        return `Quotes were stale for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("missing_delta:")) {
        return `Contracts were missing delta for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("missing_underlying_price:")) {
        return `Underlying price was missing for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("in_the_money_long_contract:")) {
        return `Primary long contracts were in the money for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("delta_out_of_range:")) {
        return `Contracts were outside the delta band for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("wide_bid_ask_spread:")) {
        return `Bid/ask spread was too wide for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("open_interest_below_min:")) {
        return `Open interest was below the planner minimum for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("invalid_market_reference:")) {
        return `Market reference price was unusable for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("debit_out_of_range:")) {
        return `Candidate debit was outside the configured dollar range for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("spread_debit_out_of_range:")) {
        return `Spread debit was outside the configured dollar range for ${reason.split(":")[1] || "the target expiry"}`;
      }
      if (reason.startsWith("no_spread_leg:")) {
        return `No matching short spread leg passed filters for ${reason.split(":")[1] || "the target expiry"}`;
      }
      return reason.replaceAll("_", " ");
    }

    function reasonParts(reason) {
      const text = String(reason || "");
      const index = text.indexOf(":");
      if (index === -1) {
        return { code: text, detail: "" };
      }
      return { code: text.slice(0, index), detail: text.slice(index + 1) };
    }

    function compactReasonLabel(code) {
      const labels = {
        invalid_bid_ask: "unusable bid/ask",
        stale_quote: "stale quotes",
        missing_delta: "missing delta",
        delta_out_of_range: "delta outside target band",
        wide_bid_ask_spread: "wide bid/ask spread",
        open_interest_below_min: "open interest below minimum",
        invalid_market_reference: "unusable market reference",
        debit_out_of_range: "debit outside configured range",
        missing_underlying_price: "missing underlying price",
        in_the_money_long_contract: "in-the-money primary leg",
        spread_debit_out_of_range: "spread debit outside configured range",
        no_spread_leg: "no matching spread leg",
        previous_successful_proposal_preserved: "previous successful proposal preserved",
        passed_long_filters: "passed long-leg filters",
        no_contracts_for_expiry: "no chain contracts returned",
        no_eligible_long_contracts: "no contracts passed filters"
      };
      return labels[code] || code.replaceAll("_", " ");
    }

    function proposalReasonHeadline(reasons) {
      if (!reasons || !reasons.length) {
        return "ready";
      }
      if (reasons.includes("no_proposals_after_filters")) {
        return "No eligible contracts after planner filters";
      }
      return friendlyReason(reasons[0]);
    }

    function proposalReasonSummary(reasons) {
      if (!reasons || !reasons.length) {
        return "";
      }
      if (reasons.length === 1) {
        return friendlyReason(reasons[0]);
      }

      const grouped = new Map();
      for (const reason of reasons) {
        if (reason === "no_proposals_after_filters") {
          continue;
        }
        const { code, detail } = reasonParts(reason);
        if (code.startsWith("proposal_generation_error")) {
          return friendlyReason(reason);
        }
        if (!grouped.has(code)) {
          grouped.set(code, new Set());
        }
        if (detail) {
          grouped.get(code).add(detail);
        }
      }

      const filterCodes = [
        "open_interest_below_min",
        "stale_quote",
        "delta_out_of_range",
        "wide_bid_ask_spread",
        "in_the_money_long_contract",
        "invalid_bid_ask",
        "missing_delta",
        "missing_underlying_price",
        "invalid_market_reference",
        "debit_out_of_range",
        "spread_debit_out_of_range",
        "no_spread_leg",
        "no_contracts_for_expiry"
      ].filter((code) => grouped.has(code));

      if (reasons.includes("no_proposals_after_filters") && filterCodes.length) {
        const expiries = new Set();
        for (const code of filterCodes) {
          for (const expiry of grouped.get(code)) {
            expiries.add(expiry);
          }
        }
        const expiryText = expiries.size ? ` Expiries checked: ${Array.from(expiries).join(", ")}.` : "";
        return `No eligible contracts. Main filters: ${filterCodes.map(compactReasonLabel).join(", ")}.${expiryText}`;
      }

      return Array.from(grouped.entries())
        .slice(0, 4)
        .map(([code, details]) => {
          const detailText = details.size ? ` (${Array.from(details).join(", ")})` : "";
          return `${compactReasonLabel(code)}${detailText}`;
        })
        .join("; ");
    }

    function setStateValue(id, label, tone) {
      const element = document.getElementById(id);
      element.textContent = label;
      element.className = `state-value ${tone || ""}`.trim();
    }

    function operatorRunState(config, summary, dataStatus, schwabStatus) {
      const latest = summary.latest_signal || null;
      const latestDecision = latest && latest.decision ? latest.decision : {};
      if (!config.options_planner_enabled) {
        return { label: "Planner Off", tone: "red" };
      }
      if (schwabStatus && schwabStatus.status === "config_error") {
        return { label: "Data Check", tone: "red" };
      }
      if (!summary.signal_count) {
        return { label: "Waiting for Signal", tone: "blue" };
      }
      if (latestDecision.status === "blocked") {
        return { label: "Latest Blocked", tone: "red" };
      }
      if (latest && latest.proposal_count) {
        return { label: "Proposal Ready", tone: "green" };
      }
      if (config.options_demo_chain_enabled) {
        return { label: "Demo Ready", tone: "amber" };
      }
      if (dataStatus.label === "READY") {
        return { label: "Chain Ready", tone: "green" };
      }
      return { label: "Proposal Pending", tone: "amber" };
    }

    function operatorDataPath(config, dataStatus) {
      if (config.options_demo_chain_enabled) {
        return "Demo Chain";
      }
      if (!config.schwab_market_data_enabled) {
        return "Provider Off";
      }
      if (dataStatus.label === "READY") {
        return "Schwab Data";
      }
      if (dataStatus.label === "ERROR") {
        return "Schwab Error";
      }
      if (dataStatus.label === "NOT SET") {
        return "Schwab Not Set";
      }
      return "Schwab Auth";
    }

    async function fetchJson(url) {
      const response = await fetch(url, { headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error(`${url} ${response.status}`);
      return response.json();
    }

    async function postJson(url, body) {
      const options = { method: "POST", headers: { "Accept": "application/json" } };
      if (body !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
      }
      const response = await fetch(url, options);
      if (!response.ok) throw new Error(`${url} ${response.status}`);
      return response.json();
    }

    async function deleteJson(url) {
      const response = await fetch(url, { method: "DELETE", headers: { "Accept": "application/json" } });
      if (!response.ok) throw new Error(`${url} ${response.status}`);
      return response.json();
    }

    function expiryChoiceLabel(value) {
      const labels = {
        "THIS_FRIDAY": "This Fri",
        "NEXT_WEEK_FRIDAY": "Next Fri"
      };
      return labels[String(value || "").toUpperCase()] || String(value || "1DTE");
    }

    function renderExpiryControls() {
      const container = document.getElementById("expiry-buttons");
      if (!container) return;
      const selected = String(dashboardSettings.expiry_label || "1DTE").toUpperCase();
      const choices = dashboardSettings.expiry_choices || ["0DTE", "1DTE", "2DTE", "3DTE", "THIS_FRIDAY", "NEXT_WEEK_FRIDAY"];
      container.innerHTML = choices.map((choice) => {
        const value = String(choice || "").toUpperCase();
        const active = value === selected;
        return `<button class="segment-button ${active ? "active" : ""}" type="button" data-expiry-label="${escapeHtml(value)}" aria-pressed="${active ? "true" : "false"}">${escapeHtml(expiryChoiceLabel(value))}</button>`;
      }).join("");
    }

    function renderAllowItmControl() {
      const checkbox = document.getElementById("allow-itm-checkbox");
      if (!checkbox) return;
      checkbox.checked = Boolean(dashboardSettings.allow_itm);
    }

    function renderMaxLossControls() {
      const container = document.getElementById("max-loss-buttons");
      if (!container) return;
      const selected = Number(dashboardSettings.max_loss_dollars || 300);
      const choices = dashboardSettings.max_loss_choices || [200, 300, 400, 500];
      container.innerHTML = choices.map((choice) => {
        const value = Number(choice);
        const active = value === selected;
        return `<button class="segment-button ${active ? "active" : ""}" type="button" data-max-loss="${value}" aria-pressed="${active ? "true" : "false"}">$${value}</button>`;
      }).join("");
    }

    function renderEntryOffsetControls() {
      const container = document.getElementById("entry-offset-buttons");
      if (!container) return;
      const selected = Number(dashboardSettings.entry_offset_cents || 30);
      const choices = dashboardSettings.entry_offset_choices || [10, 20, 30, 40, 50];
      container.innerHTML = choices.map((choice) => {
        const value = Number(choice);
        const active = value === selected;
        return `<button class="segment-button ${active ? "active" : ""}" type="button" data-entry-offset="${value}" aria-pressed="${active ? "true" : "false"}">+${value}c</button>`;
      }).join("");
    }

    function renderTargetControls() {
      const container = document.getElementById("target-percent-controls");
      if (!container) return;
      const defaults = [20, 40, 50];
      const values = Array.isArray(targetDraftValues) && targetDraftValues.length
        ? targetDraftValues
        : Array.isArray(dashboardSettings.target_percentages) && dashboardSettings.target_percentages.length
        ? dashboardSettings.target_percentages
        : defaults;
      const filled = defaults.map((fallback, index) => {
        if (Object.prototype.hasOwnProperty.call(values, index)) {
          return values[index];
        }
        return fallback;
      });
      const inputs = filled.map((value, index) =>
        `<input class="target-input" type="number" min="1" max="1000" step="1" value="${formatTargetInputValue(value, defaults[index])}" data-target-index="${index}" aria-label="Target ${index + 1} percent">`
      ).join("");
      container.innerHTML = `${inputs}<button class="copy-button" type="button" data-target-apply="true">Apply</button>`;
    }

    function formatTargetInputValue(value, fallback) {
      if (value === "") return "";
      const numeric = Number(value === undefined || value === null ? fallback : value);
      const safeValue = Number.isFinite(numeric) && numeric > 0 ? numeric : Number(fallback);
      return safeValue.toLocaleString(undefined, { maximumFractionDigits: 4, useGrouping: false });
    }

    function captureTargetDraftValues() {
      targetDraftValues = Array.from(document.querySelectorAll("#target-percent-controls .target-input"))
        .map((input) => input.value)
        .slice(0, 3);
    }

    function readTargetPercentages() {
      return Array.from(document.querySelectorAll("#target-percent-controls .target-input"))
        .map((input) => Number(input.value))
        .filter((value) => Number.isFinite(value) && value > 0);
    }

    function renderProposalSettingControls() {
      renderExpiryControls();
      renderAllowItmControl();
      renderMaxLossControls();
      renderEntryOffsetControls();
      renderTargetControls();
    }

    async function setProposalAllowItm(checked) {
      text("proposal-status", checked ? "ITM allowed" : "ATM/OTM only");
      try {
        dashboardSettings = await postJson("/dashboard/settings", { allow_itm: Boolean(checked) });
        renderProposalSettingControls();
        if (selectedSignalId) {
          await refreshSelectedProposal();
        }
      } catch (error) {
        text("proposal-status", `ITM error: ${error.message}`);
        renderProposalSettingControls();
      }
    }

    async function setProposalMaxLoss(value) {
      const selected = Number(value);
      text("proposal-status", `max loss $${selected}`);
      try {
        dashboardSettings = await postJson("/dashboard/settings", { max_loss_dollars: selected });
        renderProposalSettingControls();
        if (selectedSignalId) {
          await refreshSelectedProposal();
        }
      } catch (error) {
        text("proposal-status", `Max loss error: ${error.message}`);
        renderProposalSettingControls();
      }
    }

    async function setProposalEntryOffset(value) {
      const selected = Number(value);
      text("proposal-status", `entry +${selected}c`);
      try {
        dashboardSettings = await postJson("/dashboard/settings", { entry_offset_cents: selected });
        renderProposalSettingControls();
        if (selectedSignalId) {
          await refreshSelectedProposal();
        }
      } catch (error) {
        text("proposal-status", `Entry offset error: ${error.message}`);
        renderProposalSettingControls();
      }
    }

    async function setProposalExpiry(value) {
      const selected = String(value || "1DTE").toUpperCase();
      text("proposal-status", `expiry ${expiryChoiceLabel(selected)}`);
      try {
        dashboardSettings = await postJson("/dashboard/settings", { expiry_label: selected });
        renderProposalSettingControls();
        if (selectedSignalId) {
          await refreshSelectedProposal();
        }
      } catch (error) {
        text("proposal-status", `Expiry error: ${error.message}`);
        renderProposalSettingControls();
      }
    }

    async function setProposalTargets(values) {
      const targets = (Array.isArray(values) ? values : readTargetPercentages()).slice(0, 3);
      if (!targets.length) {
        text("proposal-status", "Target error: enter at least one target");
        renderTargetControls();
        return;
      }
      text("proposal-status", `targets ${targets.map((value) => `${value}%`).join("/")}`);
      try {
        const orderStatusProposalIds = proposalIdsNeedingOrderStatusRefresh();
        dashboardSettings = await postJson("/dashboard/settings", { target_percentages: targets });
        targetDraftValues = null;
        renderProposalSettingControls();
        if (selectedSignalId) {
          await refreshSelectedProposal({ refreshOrderStatusProposalIds: orderStatusProposalIds });
        }
      } catch (error) {
        text("proposal-status", `Target error: ${error.message}`);
        renderProposalSettingControls();
      }
    }

    function renderState(health, summary, schwabStatus) {
      const config = health.config || {};
      currentConfig = config;
      currentSchwabStatus = schwabStatus || {};
      const mode = health.execution_mode || "dry_run";
      const liveAllowed = Boolean(health.allow_live_orders);
      const dataStatus = schwabDataStatus(config, currentSchwabStatus);
      const reviewRequired = (summary.review_status_counts || {}).pending_phase_1 || 0;
      const dataPath = operatorDataPath(config, dataStatus);
      text("metric-bridge", health.status || "ok");
      text("metric-signals", summary.signal_count ?? health.signal_count ?? 0);
      text("metric-lock", liveAllowed ? "LIVE ENABLED" : "DRY RUN");
      text("metric-data", dataStatus.label);
      const runState = operatorRunState(config, summary, dataStatus, currentSchwabStatus);
      setStateValue("state-run", runState.label, runState.tone);
      setStateValue("state-review", `${reviewRequired} Pending`, reviewRequired ? "amber" : "green");
      setStateValue("state-data-path", dataPath, config.options_demo_chain_enabled ? "amber" : dataStatus.tone);
      setStateValue("state-safety", liveAllowed ? "Live Enabled" : "Orders Blocked", liveAllowed ? "red" : "green");
      document.getElementById("state-badges").innerHTML = [
        badge(mode.toUpperCase(), liveAllowed ? "red" : "green"),
        badge(liveAllowed ? "LIVE ORDERS ALLOWED" : "LIVE ORDERS BLOCKED", liveAllowed ? "red" : "green"),
        badge(config.manual_review_required ? "MANUAL REVIEW REQUIRED" : "AUTO REVIEW", config.manual_review_required ? "amber" : "blue"),
        badge(config.trading_enabled ? "TRADING GATE ON" : "TRADING GATE OFF", config.trading_enabled ? "amber" : "green"),
        badge(config.options_planner_enabled ? "PLANNER ON" : "PLANNER OFF", config.options_planner_enabled ? "blue" : "red"),
        config.options_demo_chain_enabled ? badge("DEMO CHAIN ON", "amber") : "",
        badge(dataStatus.badge, dataStatus.tone)
      ].filter(Boolean).join("");

      document.getElementById("demo-signal-button").style.display = config.options_demo_chain_enabled
        ? "inline-flex"
        : "none";
      updateSoundControls();

      const schwabNotice = document.getElementById("schwab-status-notice");
      const notes = currentSchwabStatus.notes || [];
      if (notes.length || currentSchwabStatus.error) {
        schwabNotice.style.display = "block";
        schwabNotice.textContent = [currentSchwabStatus.error, ...notes].filter(Boolean).join(" ");
      } else {
        schwabNotice.style.display = "none";
        schwabNotice.textContent = "";
      }
    }

    function plannerScoped(record) {
      const payload = record.payload || {};
      const allowed = currentConfig.options_allowed_symbols || [];
      if (!allowed.length) return true;
      return allowed.includes(optionSymbolFor(payload.symbol));
    }

    function optionSymbolFor(symbol) {
      const normalized = String(symbol || "").toUpperCase().replace("$", "").trim();
      const symbolMap = currentConfig.options_symbol_map || {};
      return symbolMap[normalized] || normalized;
    }

    function schwabChainCheckRequest() {
      const record = signalById.get(selectedSignalId) || null;
      const payload = record?.payload || {};
      const sourceSymbol = String(payload.symbol || "SPY").toUpperCase().replace("$", "").trim();
      const symbol = optionSymbolFor(sourceSymbol || "SPY") || "SPY";
      const rawDirection = String(payload.direction || "long").toLowerCase().trim();
      const direction = rawDirection === "short" ? "short" : "long";
      const label = record
        ? `${sourceSymbol || symbol} ${direction} -> ${symbol}`
        : "SPY long fallback";
      return { symbol, direction, label };
    }

    function preferredSignalForPlanner(signals) {
      return signals.find((record) => Number(record.proposal_count || 0) > 0)
        || signals.find((record) => plannerScoped(record))
        || signals[0];
    }

    function proposalCell(record) {
      const count = Number(record.proposal_count || 0);
      if (count > 0) {
        return badge(`${count} ready`, "green");
      }
      return "0";
    }

    function updateShowProposalButton(signals) {
      const button = document.getElementById("show-proposal-button");
      const proposalRecord = signals.find((record) => Number(record.proposal_count || 0) > 0);
      const scopedRecord = signals.find((record) => plannerScoped(record));
      const target = proposalRecord || scopedRecord || null;
      bestProposalSignalId = target ? target.id : null;
      button.disabled = !bestProposalSignalId || bestProposalSignalId === selectedSignalId;
      button.textContent = proposalRecord ? "Show Proposal" : "Show SPY";
    }

    function renderSignals(list, options = {}) {
      const body = document.getElementById("signals-body");
      const signals = list.signals || [];
      const preserveSelectedSignal = Boolean(options.preserveSelectedSignal);
      updateProposalAlertState(signals);
      text("signals-status", `${list.returned_count || 0} shown`);
      document.getElementById("proposal-refresh-button").disabled = !signals.length;
      if (!signals.length) {
        body.innerHTML = `<tr><td colspan="7"><div class="empty">No signals received yet</div></td></tr>`;
        selectedSignalId = null;
        bestProposalSignalId = null;
        signalById = new Map();
        updateShowProposalButton([]);
        return null;
      }

      signalById = new Map(signals.map((record) => [record.id, record]));

      const selectedStillVisible = signals.some((record) => record.id === selectedSignalId);
      const selectedRecord = signalById.get(selectedSignalId);
      const canPreserveSelectedSignal = preserveSelectedSignal && selectedSignalId && selectedStillVisible;
      const shouldAutoSelect =
        !canPreserveSelectedSignal && (
          !selectedSignalId
          || !selectedStillVisible
          || (!userSelectedSignal && selectedRecord && !plannerScoped(selectedRecord) && signals.some(plannerScoped))
          || (!userSelectedSignal && selectedRecord && Number(selectedRecord.proposal_count || 0) === 0 && signals.some((record) => Number(record.proposal_count || 0) > 0))
        );
      if (shouldAutoSelect) {
        const preferred = preferredSignalForPlanner(signals);
        selectedSignalId = preferred ? preferred.id : signals[0].id;
        userSelectedSignal = false;
      }
      updateShowProposalButton(signals);

      body.innerHTML = signals.map((record) => {
        const payload = record.payload || {};
        const decision = record.decision || {};
        const classes = [
          "signal-row",
          record.id === selectedSignalId ? "selected" : "",
          Number(record.proposal_count || 0) > 0 ? "has-proposal" : ""
        ].filter(Boolean).join(" ");
        return `<tr class="${classes}" tabindex="0" data-signal-id="${escapeHtml(record.id)}">
          <td>${escapeHtml(fmtTime(record.received_at))}</td>
          <td><strong>${escapeHtml(payload.symbol || "--")}</strong></td>
          <td>${escapeHtml(payload.direction || "--")}</td>
          <td>${sourceBadge(payload.source_indicator)}</td>
          <td>${badge(decision.status || "unknown", decisionTone(decision.status))}</td>
          <td>${proposalCell(record)}</td>
          <td>${escapeHtml(record.review_status || record.status || "--")}</td>
        </tr>`;
      }).join("");

      document.querySelectorAll(".signal-row").forEach((row) => {
        const activate = () => {
          selectedSignalId = row.dataset.signalId;
          userSelectedSignal = true;
          document.querySelectorAll(".signal-row").forEach((item) => item.classList.remove("selected"));
          row.classList.add("selected");
          loadProposal(selectedSignalId, signalById.get(selectedSignalId));
        };
        row.addEventListener("click", activate);
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate();
          }
        });
      });

      return signals.find((record) => record.id === selectedSignalId) || signals[0];
    }

    async function refreshSignalListMetadata(options = {}) {
      const previousSelectedSignalId = selectedSignalId;
      const signals = await fetchJson("/signals?limit=25");
      if (options.preserveSelectedSignal && previousSelectedSignalId) {
        selectedSignalId = previousSelectedSignalId;
      }
      return renderSignals(signals, options);
    }

    function proposalTitle(proposal) {
      const legs = proposal.legs || [];
      if (!legs.length) return proposal.structure || "proposal";
      return legs.map((leg) => `${leg.action} ${leg.qty} ${leg.symbol} ${leg.expiry} ${leg.strike}${leg.right === "CALL" ? "C" : "P"}`).join(" / ");
    }

    function proposalUnitLimit(proposal) {
      const sendLimit = Number(proposal?.send_limit_price || 0);
      if (sendLimit > 0) return sendLimit;
      const quantity = Number(proposal?.quantity || 0);
      const debit = Number(proposal?.debit || 0);
      if (quantity > 0 && debit > 0) return debit / (quantity * 100);
      return Number(proposal?.natural_limit_price || 0);
    }

    function selectedProposalQuantity(proposal) {
      const override = Number(proposalQuantityOverrides.get(proposal.id) || 1);
      return Math.max(1, Math.min(MAX_PROPOSAL_QUANTITY, override));
    }

    function formatTosStrike(strike) {
      const value = Number(strike || 0);
      return Number.isInteger(value) ? String(value) : String(strike);
    }

    function formatTosExpiry(expiry) {
      const parts = String(expiry || "").split("-").map((part) => Number(part));
      const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
      if (parts.length !== 3 || parts.some((part) => Number.isNaN(part))) return String(expiry || "");
      return `${String(parts[2]).padStart(2, "0")} ${months[Math.max(0, Math.min(11, parts[1] - 1))]} ${String(parts[0]).slice(-2)}`;
    }

    function tosOrderLine(proposal, quantity, limitPrice) {
      const legs = proposal.legs || [];
      const structure = proposal.structure === "debit_vertical" ? "VERTICAL" : "SINGLE";
      const strikes = legs.map((leg) => formatTosStrike(leg.strike)).join("/");
      const right = legs[0]?.right || "CALL";
      return `BUY +${quantity} ${structure} ${String(proposal.symbol || "").toUpperCase()} 100 ${formatTosExpiry(proposal.expiry)} ${strikes} ${right} @${Number(limitPrice || 0).toFixed(2)} LMT`;
    }

    function tosExitOrderLine(proposal, quantity, limitPrice) {
      const legs = proposal.legs || [];
      const structure = proposal.structure === "debit_vertical" ? "VERTICAL" : "SINGLE";
      const strikes = legs.map((leg) => formatTosStrike(leg.strike)).join("/");
      const right = legs[0]?.right || "CALL";
      return `SELL -${quantity} ${structure} ${String(proposal.symbol || "").toUpperCase()} 100 ${formatTosExpiry(proposal.expiry)} ${strikes} ${right} @${Number(limitPrice || 0).toFixed(2)} LMT GTC`;
    }

    function targetPercentagesForQuantity(quantity) {
      const configured = Array.isArray(dashboardSettings.target_percentages) ? dashboardSettings.target_percentages : [];
      const targets = configured.map((value) => Number(value)).filter((value) => value > 0);
      const fallback = [20, 40, 50];
      while (targets.length < quantity && fallback[targets.length] != null) {
        targets.push(fallback[targets.length]);
      }
      return targets.slice(0, Math.max(1, Math.min(3, quantity)));
    }

    function exitTargetsForQuantity(proposal, quantity, entryLimit) {
      let remaining = quantity;
      return targetPercentagesForQuantity(quantity).map((percent, index, percentages) => {
        const targetQty = index === percentages.length - 1 ? remaining : 1;
        remaining -= targetQty;
        let targetLimit = Number(entryLimit || 0) * (1 + percent / 100);
        if (proposal.structure === "debit_vertical" && Number(proposal.width || 0) > 0) {
          targetLimit = Math.min(targetLimit, Number(proposal.width));
        }
        targetLimit = Math.round(targetLimit * 100) / 100;
        return {
          qty: targetQty,
          target_percent: percent,
          entry_limit_price: Number(entryLimit || 0),
          target_limit_price: targetLimit,
          estimated_profit: Math.max(0, Math.round((targetLimit - Number(entryLimit || 0)) * 100 * targetQty * 100) / 100),
          tos_exit_order_line: tosExitOrderLine(proposal, targetQty, targetLimit)
        };
      });
    }

    function adjustedProposalForQuantity(proposal) {
      const quantity = selectedProposalQuantity(proposal);
      const unitLimit = proposalUnitLimit(proposal);
      const naturalLimit = Number(proposal.natural_limit_price || unitLimit || 0);
      const debit = Math.round(unitLimit * 100 * quantity * 100) / 100;
      const naturalDebit = Math.round(naturalLimit * 100 * quantity * 100) / 100;
      const legs = (proposal.legs || []).map((leg) => ({ ...leg, qty: quantity }));
      return {
        ...proposal,
        quantity,
        legs,
        debit,
        max_loss: debit,
        natural_debit: naturalDebit,
        send_limit_price: unitLimit,
        tos_order_line: tosOrderLine({ ...proposal, legs }, quantity, unitLimit),
        exit_targets: exitTargetsForQuantity({ ...proposal, legs }, quantity, unitLimit)
      };
    }

    function renderProposalQuantityControl(proposal) {
      const selected = selectedProposalQuantity(proposal);
      const submitted = proposalHasSubmittedEntryOrder(proposal.id);
      const buttons = Array.from({ length: MAX_PROPOSAL_QUANTITY }, (_value, index) => index + 1).map((quantity) => {
        const disabled = submitted;
        return `<button class="segment-button proposal-quantity-button ${quantity === selected ? "active" : ""}" type="button" data-proposal-id="${escapeHtml(proposal.id)}" data-quantity="${quantity}" ${disabled ? "disabled" : ""}>${quantity}</button>`;
      }).join("");
      return `<div class="proposal-quantity-control"><span class="label">Qty</span><span class="segmented proposal-qty-segmented">${buttons}</span></div>`;
    }

    function renderProposalGuide(result, selectedSignal) {
      const guide = document.getElementById("proposal-guide");
      const proposals = result.proposals || [];
      if (proposals.length) {
        guide.style.display = "none";
        guide.textContent = "";
        return;
      }
      if (selectedSignal && !plannerScoped(selectedSignal) && bestProposalSignalId && bestProposalSignalId !== selectedSignal.id) {
        guide.style.display = "block";
        const payload = selectedSignal.payload || {};
        guide.textContent = `${payload.symbol || "Selected signal"} is outside planner scope. A SPY proposal is available.`;
        return;
      }
      guide.style.display = "none";
      guide.textContent = "";
    }

    function formatCount(value) {
      if (value == null || Number.isNaN(Number(value))) {
        return "--";
      }
      return Number(value).toLocaleString("en-US");
    }

    function proposalLegText(leg) {
      const side = leg.right === "CALL" ? "C" : "P";
      const price = Number(leg.price || 0).toFixed(2);
      return `${leg.action} ${leg.qty} ${leg.symbol} ${leg.expiry} ${leg.strike}${side} @ ${price} | Open Int ${formatCount(leg.open_interest)} | Volume ${formatCount(leg.volume)}`;
    }

    function displaySourceName(value) {
      const raw = String(value || "").trim();
      const compact = raw.replaceAll(" ", "").replace("_DoubleArrow", "").toLowerCase();
      if (compact === "ultimateaipro" || compact === "ultimateaiprodoublearrow") {
        return "UltimateAI Pro";
      }
      return raw || "Unknown Source";
    }

    function proposalOrderNote(proposal, selectedSignal) {
      const payload = selectedSignal?.payload || {};
      const source = displaySourceName(payload.source_indicator || payload.strategy);
      const signalTime = fmtTime(payload.timestamp || selectedSignal?.received_at);
      const symbol = proposal?.symbol || payload.symbol || "--";
      const direction = proposal?.direction || payload.direction || "--";
      const proposalTargets = Array.isArray(proposal?.exit_targets)
        ? proposal.exit_targets.map((target) => target.target_percent)
        : [];
      const targets = proposalTargets.length
        ? proposalTargets
            .filter((target) => Number(target) > 0)
            .map((target) => `${Number(target).toLocaleString(undefined, { maximumFractionDigits: 4 })}%`)
        : (payload.profit_target_percentages || [])
            .filter((target) => Number(target) > 0)
            .map((target) => `${Number(target).toLocaleString(undefined, { maximumFractionDigits: 4 })}%`);
      const targetText = targets.length ? ` | Targets ${targets.join("/")}` : "";
      return `${source} | Signal Time ${signalTime} | ${symbol} ${direction}${targetText}`;
    }

    function renderExitPlan(proposal) {
      const targets = Array.isArray(proposal.exit_targets) ? proposal.exit_targets : [];
      if (!targets.length) {
        return "";
      }
      const orderStatus = proposalOrderStatuses.get(proposal.id) || null;
      const statusRows = renderProposalOrderStatus(orderStatus);
      const rows = targets.map((target, targetIndex) => {
        const qty = Number(target.qty || 0);
        const percent = Number(target.target_percent || 0);
        const filledTarget = firstFilledExitTarget(orderStatus, targetIndex);
        const targetLimit = Number((filledTarget && filledTarget.target_limit_price) || target.target_limit_price || 0);
        const estimatedProfit = Number((filledTarget && filledTarget.estimated_profit) || target.estimated_profit || 0);
        const entryFill = filledTarget && filledTarget.entry_fill_price
          ? ` | fill ${Number(filledTarget.entry_fill_price).toFixed(2)}`
          : "";
        const note = target.note ? ` (${target.note})` : "";
        const sellLineValue = (filledTarget && filledTarget.tos_exit_order_line) || target.tos_exit_order_line || "";
        const canSendExit = Boolean(filledTarget);
        const exitResponse = exitSendResponses.get(exitSendKey(proposal.id, targetIndex)) || null;
        const hasSubmittedExit = Boolean(exitResponse && (exitResponse.account_results || []).some((item) => item.status === "submitted"));
        const hasExistingExit = Boolean(exitResponse && (exitResponse.account_results || []).some((item) =>
          (item.reasons || []).some((reason) => String(reason).startsWith("target_exit_already_") || String(reason).startsWith("target_exit_status_unverified:"))
        ));
        const sendDisabled = !canSendExit || hasSubmittedExit || hasExistingExit;
        const sendLabel = !canSendExit ? "Get fill first" : hasSubmittedExit ? "SELL sent" : hasExistingExit ? "Already sent" : "Send SELL to Schwab";
        const exitSendStatus = exitResponse
          ? `<span class="exit-send-confirmation ${hasSubmittedExit || hasExistingExit ? "submitted" : ""}">${escapeHtml(sendStatusText(exitResponse))}</span>`
          : "";
        const sellLine = sellLineValue
          ? `<span class="exit-order-row"><span class="exit-order-line">${escapeHtml(sellLineValue)}</span><button class="copy-button copy-exit-tos-button" type="button" data-copy-label="Copy SELL" data-tos="${escapeHtml(sellLineValue)}">Copy SELL</button><button class="copy-button send-button send-exit-to-schwab-button ${hasSubmittedExit || hasExistingExit ? "sent" : ""}" type="button" data-proposal-id="${escapeHtml(proposal.id)}" data-target-index="${targetIndex}" ${sendDisabled ? "disabled" : ""}>${sendLabel}</button></span>${exitSendStatus}`
          : "";
        return `<span class="exit-target">${escapeHtml(`${qty} @ +${percent.toLocaleString(undefined, { maximumFractionDigits: 4 })}% -> ${targetLimit.toFixed(2)}${entryFill} | est +$${estimatedProfit.toFixed(2)}${note}`)}${sellLine}</span>`;
      }).join("");
      return `<div class="exit-plan"><div><span class="label">Exit Plan</span> <span class="exit-plan-note">${orderStatus && orderStatus.has_filled_accounts ? "fill received; target send enabled" : "target exits not sent yet"}</span><button class="copy-button refresh-order-status-button" type="button" data-proposal-id="${escapeHtml(proposal.id)}">Get Order Info</button></div>${statusRows}<div class="exit-targets">${rows}</div></div>`;
    }

    function exitSendKey(proposalId, targetIndex) {
      return `${proposalId}:${Number(targetIndex)}`;
    }

    function firstFilledExitTarget(orderStatus, targetIndex) {
      if (!orderStatus || !Array.isArray(orderStatus.account_statuses)) return null;
      for (const account of orderStatus.account_statuses) {
        if (!["filled", "partial"].includes(account.status) || !account.average_fill_price) continue;
        const target = (account.exit_targets || []).find((item) => Number(item.target_index) === Number(targetIndex));
        if (target) return target;
      }
      return null;
    }

    function renderProposalOrderStatus(orderStatus) {
      if (!orderStatus) {
        return `<div class="order-note">Entry order fill has not been checked yet.</div>`;
      }
      const notes = (orderStatus.notes || []).join(" ");
      const rows = (orderStatus.account_statuses || []).map((account) => {
        const fill = account.average_fill_price == null ? "--" : Number(account.average_fill_price).toFixed(2);
        const qty = Number(account.filled_quantity || 0).toLocaleString(undefined, { maximumFractionDigits: 4 });
        const broker = account.broker_order_id ? ` | order ${account.broker_order_id}` : "";
        const extra = (account.notes || []).length ? ` | ${(account.notes || []).join(" ")}` : "";
        return `${account.account_label}: ${account.status}${broker} | filled ${qty} @ ${fill}${extra}`;
      }).join(" | ");
      return `<div class="order-note"><span class="label">Entry Order Info</span> ${escapeHtml(rows || notes || "No submitted entry order found for this proposal.")}</div>`;
    }

    function proposalHasSubmittedEntryOrder(proposalId) {
      const sendResponse = entrySendResponses.get(proposalId) || null;
      if (sendResponse && (sendResponse.account_results || []).some((item) => item.status === "submitted")) {
        return true;
      }
      const orderStatus = proposalOrderStatuses.get(proposalId) || null;
      return Boolean(orderStatus && (orderStatus.account_statuses || []).some((item) => item.broker_order_id));
    }

    function renderOrderNote(orderNote, proposalId) {
      const copyButton = proposalHasSubmittedEntryOrder(proposalId)
        ? ` <button class="copy-button copy-note-button" type="button" data-copy-label="Copy Note" data-note="${escapeHtml(orderNote)}">Copy Note</button>`
        : "";
      return `<div class="order-note"><span class="label">Order Note</span> ${escapeHtml(orderNote)}${copyButton}</div>`;
    }

    function formatQuoteAge(seconds) {
      if (seconds == null || Number.isNaN(Number(seconds))) {
        return "--";
      }
      const total = Math.max(0, Math.round(Number(seconds)));
      if (total < 60) {
        return `${total}s`;
      }
      const minutes = Math.floor(total / 60);
      if (minutes < 60) {
        return `${minutes}m ${total % 60}s`;
      }
      const hours = Math.floor(minutes / 60);
      return `${hours}h ${minutes % 60}m`;
    }

    function renderQuoteFreshness(result) {
      const container = document.getElementById("quote-freshness");
      const freshness = result.quote_freshness || {};
      if (!freshness.checked_contract_count) {
        container.innerHTML = "";
        return;
      }
      const staleCount = freshness.stale_contract_count || 0;
      const total = freshness.checked_contract_count || 0;
      const status = String(freshness.status || "not_checked").replaceAll("_", " ").toUpperCase();
      const statusTone = freshness.status === "fresh" ? "green" : freshness.status === "mixed" ? "amber" : "red";
      container.innerHTML = `
        <div class="freshness-item">
          <div class="label">Quote Freshness</div>
          <div class="freshness-value">${badge(status, statusTone)}</div>
        </div>
        <div class="freshness-item">
          <div class="label">Freshest Quote</div>
          <div class="freshness-value">${escapeHtml(fmtTime(freshness.freshest_quote_time))}</div>
        </div>
        <div class="freshness-item">
          <div class="label">Quote Age</div>
          <div class="freshness-value">${escapeHtml(formatQuoteAge(freshness.freshest_quote_age_seconds))} / ${escapeHtml(staleCount)} of ${escapeHtml(total)} stale</div>
        </div>`;
    }

    function renderCandidateDiagnostics(result) {
      const container = document.getElementById("candidate-diagnostics");
      const candidates = result.candidate_diagnostics || [];
      if (!candidates.length || (result.proposals || []).length) {
        container.innerHTML = "";
        return;
      }

      container.innerHTML = candidates.slice(0, 6).map((candidate) => {
        const strike = Number(candidate.strike || 0).toFixed(1);
        const bid = candidate.bid == null ? "--" : Number(candidate.bid).toFixed(2);
        const ask = candidate.ask == null ? "--" : Number(candidate.ask).toFixed(2);
        const delta = candidate.delta == null ? "--" : Number(candidate.delta).toFixed(2);
        const oi = candidate.open_interest == null ? "--" : candidate.open_interest;
        const volume = candidate.volume == null ? "--" : candidate.volume;
        const reasons = (candidate.reasons || []).map(compactReasonLabel).join(", ") || "blocked";
        return `<article class="candidate">
          <div class="candidate-title">
            <span>${escapeHtml(`${strike}${candidate.right === "PUT" ? "P" : "C"} ${candidate.expiry || ""}`)}</span>
            ${badge("BLOCKED", "amber")}
          </div>
          <div class="candidate-meta">${escapeHtml(`Bid/Ask ${bid} / ${ask} | Delta ${delta} | Open Int ${oi} | Volume ${volume} | Quote ${fmtTime(candidate.quote_time)}`)}</div>
          <div class="candidate-reasons">${escapeHtml(reasons)}</div>
        </article>`;
      }).join("");
    }

    async function copyTosText(value, button) {
      const textToCopy = String(value || "");
      if (!textToCopy) return;
      const candidateField = button ? button.closest(".proposal")?.querySelector(".tos-copy-field") : null;
      const field = candidateField && candidateField.value === textToCopy ? candidateField : null;
      let copied = false;
      try {
        if (navigator.clipboard && window.isSecureContext) {
          await navigator.clipboard.writeText(textToCopy);
          copied = true;
        }
      } catch (error) {
        copied = false;
      }
      if (!copied && field) {
        field.focus();
        field.select();
        try {
          copied = document.execCommand("copy");
        } catch (error) {
          copied = false;
        }
      }
      if (!copied && !field) {
        try {
          const textarea = document.createElement("textarea");
          textarea.value = textToCopy;
          textarea.setAttribute("readonly", "");
          textarea.style.position = "fixed";
          textarea.style.left = "-9999px";
          document.body.appendChild(textarea);
          textarea.select();
          copied = document.execCommand("copy");
          document.body.removeChild(textarea);
        } catch (error) {
          copied = false;
        }
      }
      if (button) {
        const copyLabel = button.dataset.copyLabel || "Copy TOS";
        button.textContent = copied ? "Copied" : "Selected";
        button.classList.toggle("copied", copied);
        setTimeout(() => {
          button.textContent = copyLabel;
          button.classList.remove("copied");
        }, 1400);
      }
    }

    function attachTosCopyButtons() {
      document.querySelectorAll(".copy-tos-button, .copy-exit-tos-button").forEach((button) => {
        button.addEventListener("click", () => copyTosText(button.dataset.tos || "", button));
      });
      document.querySelectorAll(".copy-note-button").forEach((button) => {
        button.addEventListener("click", () => copyTosText(button.dataset.note || "", button));
      });
      document.querySelectorAll(".refresh-order-status-button").forEach((button) => {
        button.addEventListener("click", () => refreshProposalOrderStatus(button.dataset.proposalId || "", button));
      });
      document.querySelectorAll(".tos-copy-field").forEach((field) => {
        field.addEventListener("focus", () => field.select());
        field.addEventListener("click", () => field.select());
      });
      document.querySelectorAll(".send-to-schwab-button").forEach((button) => {
        button.addEventListener("click", () => sendProposalToSchwab(button.dataset.proposalId || "", button));
      });
      document.querySelectorAll(".send-exit-to-schwab-button").forEach((button) => {
        button.addEventListener("click", () => sendExitToSchwab(button.dataset.proposalId || "", Number(button.dataset.targetIndex || 0), button));
      });
      document.querySelectorAll(".proposal-quantity-button").forEach((button) => {
        button.addEventListener("click", () => {
          const proposalId = button.dataset.proposalId || "";
          const quantity = Number(button.dataset.quantity || 1);
          if (!proposalId || button.disabled) return;
          proposalQuantityOverrides.set(proposalId, quantity);
          renderProposalResult(currentProposalResult || { proposals: [], blocked_reasons: [] }, signalById.get(selectedSignalId) || null);
        });
      });
      document.querySelectorAll(".proposal-account-checkbox").forEach((checkbox) => {
        checkbox.addEventListener("change", () => updateAccountSelectionFromDashboard(checkbox));
      });
    }

    function proposalNeedsSpreadApproval(proposal) {
      return proposal.structure === "debit_vertical";
    }

    function accountEligibility(account, proposal) {
      if (!account.enabled) {
        return { eligible: false, reason: "disabled" };
      }
      if (proposalNeedsSpreadApproval(proposal) && !account.supports_spreads) {
        return { eligible: false, reason: "spreads not allowed" };
      }
      return { eligible: true, reason: "" };
    }

    function proposalRequiredCost(proposal) {
      const maxLoss = Number(proposal?.max_loss || 0);
      const debit = Number(proposal?.debit || 0);
      if (Number.isFinite(maxLoss) && maxLoss > 0) return maxLoss;
      if (Number.isFinite(debit) && debit > 0) return debit;
      return 0;
    }

    function accountAvailableToTrade(account) {
      const balance = account?.balance || {};
      const value = Number(balance.available_to_trade);
      return Number.isFinite(value) ? value : null;
    }

    function accountBalanceInfo(account, proposal) {
      const balance = account?.balance || null;
      const required = proposalRequiredCost(proposal);
      if (!balance) {
        return { tone: "neutral", routeClass: "", label: "Avail --", meta: "balance unavailable" };
      }
      if (balance.error) {
        return { tone: "red", routeClass: "balance-low", label: "Balance error", meta: "balance lookup failed" };
      }
      const available = accountAvailableToTrade(account);
      if (available == null) {
        return { tone: "neutral", routeClass: "", label: "Avail --", meta: "available balance unavailable" };
      }
      const ok = required <= 0 || available >= required;
      const buyingPower = Number(balance.buying_power);
      const buyingPowerText = Number.isFinite(buyingPower) ? ` | buying power ${fmtMoney(buyingPower)}` : "";
      const label = `Avail ${fmtMoney(available)}`;
      const needText = required > 0 ? ` | needed ${fmtMoney(required)}` : "";
      const meta = `available ${fmtMoney(available)}${needText}${buyingPowerText}`;
      return {
        tone: ok ? "green" : "red",
        routeClass: ok ? "balance-ok" : "balance-low",
        label,
        meta
      };
    }

    function renderAccountRouting(proposal) {
      if (!schwabAccounts.length) {
        const note = schwabAccountNotes.length
          ? schwabAccountNotes.join(" ")
          : "No Schwab accounts configured or discovered for sending.";
        return `<div class="account-routing"><div class="label">Accounts to Send</div><div class="account-route-meta">${escapeHtml(note)}</div><div class="send-status" data-send-status-for="${escapeHtml(proposal.id)}"></div></div>`;
      }
      const rows = schwabAccounts.map((account) => {
        const eligibility = accountEligibility(account, proposal);
        const checked = selectedAccountIds.has(account.id) && eligibility.eligible;
        const disabled = !eligibility.eligible;
        const type = account.account_type === "unknown" ? "account" : account.account_type;
        const spreadText = account.supports_spreads ? "spreads ok" : "single-leg only";
        const orderText = account.order_configured ? "order hash set" : "order hash missing";
        const sourceText = account.source === "discovered" ? "discovered" : "configured";
        const labelText = account.account_number
          ? `${account.account_number} (${account.label || account.id})`
          : (account.label || account.id);
        const balanceInfo = accountBalanceInfo(account, proposal);
        const reason = eligibility.reason ? ` | ${eligibility.reason}` : "";
        const balanceMeta = balanceInfo.meta ? ` | ${balanceInfo.meta}` : "";
        return `<label class="account-route ${disabled ? "blocked" : ""} ${balanceInfo.routeClass}">
          <input class="proposal-account-checkbox" type="checkbox" data-account-id="${escapeHtml(account.id)}" data-proposal-id="${escapeHtml(proposal.id)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}>
          <span>
            <span class="account-route-label">${escapeHtml(labelText)}</span>
            <span class="account-route-meta">${escapeHtml(`${type} | ${spreadText} | ${orderText} | ${sourceText}${reason}${balanceMeta}`)}</span>
          </span>
          <span class="account-route-actions">
            ${disabled ? badge("BLOCKED", "amber") : ""}
            <span class="account-balance ${balanceInfo.tone}">${escapeHtml(balanceInfo.label)}</span>
          </span>
        </label>`;
      }).join("");
      return `<div class="account-routing"><div class="label">Accounts to Send</div>${rows}<div class="send-status" data-send-status-for="${escapeHtml(proposal.id)}"></div></div>`;
    }

    function updateAccountCheckboxes() {
      document.querySelectorAll(".proposal-account-checkbox").forEach((checkbox) => {
        checkbox.checked = !checkbox.disabled && selectedAccountIds.has(checkbox.dataset.accountId || "");
      });
    }

    async function persistAccountSelection() {
      try {
        const result = await postJson("/schwab/accounts/selection", {
          selected_account_ids: Array.from(selectedAccountIds)
        });
        schwabAccounts = result.accounts || [];
        schwabAccountNotes = result.notes || [];
        selectedAccountIds = new Set(result.selected_account_ids || []);
        updateAccountCheckboxes();
      } catch (error) {
        document.querySelectorAll(".send-status").forEach((item) => {
          item.textContent = `Account selection save failed: ${error.message}`;
        });
      }
    }

    function updateAccountSelectionFromDashboard(changedCheckbox) {
      const accountId = changedCheckbox ? (changedCheckbox.dataset.accountId || "") : "";
      if (accountId) {
        if (changedCheckbox.checked) {
          selectedAccountIds.add(accountId);
        } else {
          selectedAccountIds.delete(accountId);
        }
      } else {
        const next = new Set();
        document.querySelectorAll(".proposal-account-checkbox:checked").forEach((checkbox) => {
          next.add(checkbox.dataset.accountId || "");
        });
        selectedAccountIds = next;
      }
      updateAccountCheckboxes();
      persistAccountSelection();
    }

    function sendStatusText(response) {
      const results = response.account_results || [];
      const note = response.order_note ? ` | Note: ${response.order_note}` : "";
      if (!results.length) {
        return `${(response.notes || []).join(" ") || "No accounts selected."}${note}`;
      }
      const summary = results.map((item) => {
        if (item.status === "submitted") {
          const orderId = item.broker_order_id ? ` ${item.broker_order_id}` : "";
          return `${item.account_label}: submitted${orderId}`;
        }
        if (item.status === "dry_run" && item.order_payload) {
          return `${item.account_label}: order payload ready; live gate off`;
        }
        const reasons = (item.reasons || []).map(formatSendReason).join(", ") || item.status;
        return `${item.account_label}: ${reasons}`;
      }).join(" | ");
      return `${summary}${note}`;
    }

    function formatSendReason(reason) {
      const raw = String(reason || "");
      const parts = raw.split(":");
      if (raw.startsWith("target_exit_already_active:")) {
        return `target exit already active ${parts[1] || ""}${parts[2] ? ` (${parts[2]})` : ""}`.trim();
      }
      if (raw.startsWith("target_exit_already_filled:")) {
        return `target exit already filled ${parts[1] || ""}${parts[2] ? ` (${parts[2]})` : ""}`.trim();
      }
      if (raw.startsWith("target_exit_status_unverified:")) {
        return `existing target exit status unverified ${parts[1] || ""}`.trim();
      }
      if (raw === "schwab_exit_order_submitted") return "target exit submitted";
      if (raw === "schwab_order_submitted") return "order submitted";
      return raw;
    }

    function proposalEntryLimitText(proposal) {
      const natural = Number(proposal.natural_limit_price || 0);
      const sendLimit = Number(proposal.send_limit_price || 0);
      const naturalDebit = Number(proposal.natural_debit || 0);
      const label = proposal.structure === "single" ? "Ask" : "Natural debit";
      const parts = [];
      if (natural > 0) parts.push(`${label}: ${natural.toFixed(2)}`);
      if (naturalDebit > 0) parts.push(`Natural max: $${naturalDebit.toFixed(2)}`);
      if (sendLimit > 0) parts.push(`Send Limit: ${sendLimit.toFixed(2)}`);
      if (proposal.price_protection) parts.push(proposal.price_protection);
      return parts.join(" | ");
    }

    function proposalExecutionBadge() {
      const liveOrderEnabled = currentConfig.execution_mode === "live"
        && Boolean(currentConfig.allow_live_orders)
        && Boolean(currentConfig.trading_enabled);
      return liveOrderEnabled ? badge("LIVE READY", "red") : badge("DRY RUN", "green");
    }

    async function refreshProposalOrderStatus(proposalId, button) {
      if (!proposalId || !selectedSignalId) return null;
      if (button) {
        button.disabled = true;
        button.textContent = "Checking...";
      }
      try {
        const result = await fetchJson(`/signals/${encodeURIComponent(selectedSignalId)}/proposals/${encodeURIComponent(proposalId)}/orders/status`);
        proposalOrderStatuses.set(proposalId, result);
        renderProposalResult(currentProposalResult || { proposals: [], blocked_reasons: [] }, signalById.get(selectedSignalId) || null);
        return result;
      } catch (error) {
        const existing = proposalOrderStatuses.get(proposalId) || { account_statuses: [], notes: [] };
        existing.notes = [`Order info error: ${error.message}`];
        proposalOrderStatuses.set(proposalId, existing);
        renderProposalResult(currentProposalResult || { proposals: [], blocked_reasons: [] }, signalById.get(selectedSignalId) || null);
        return null;
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = "Get Order Info";
        }
      }
    }

    function proposalIdsNeedingOrderStatusRefresh() {
      const proposals = currentProposalResult?.proposals || [];
      const ids = proposals
        .map((proposal) => proposal.id)
        .filter((proposalId) => {
          const status = proposalOrderStatuses.get(proposalId) || null;
          return proposalHasSubmittedEntryOrder(proposalId) || Boolean(status && status.has_filled_accounts);
        });
      return Array.from(new Set(ids));
    }

    async function refreshOrderStatusesForProposalIds(proposalIds) {
      const activeProposalIds = new Set((currentProposalResult?.proposals || []).map((proposal) => proposal.id));
      for (const proposalId of Array.from(new Set(proposalIds || []))) {
        if (activeProposalIds.has(proposalId)) {
          await refreshProposalOrderStatus(proposalId, null);
        }
      }
    }

    async function sendExitToSchwab(proposalId, targetIndex, button) {
      if (!proposalId || !selectedSignalId) return;
      const status = document.querySelector(`[data-send-status-for="${CSS.escape(proposalId)}"]`);
      const proposal = (currentProposalResult?.proposals || []).find((item) => item.id === proposalId);
      const selectedSignal = signalById.get(selectedSignalId) || null;
      let orderStatus = proposalOrderStatuses.get(proposalId) || null;
      if (!orderStatus || !orderStatus.has_filled_accounts) {
        orderStatus = await refreshProposalOrderStatus(proposalId, button);
      }
      if (!orderStatus || !orderStatus.has_filled_accounts) {
        if (status) status.textContent = "Entry fill not available yet. Refresh order info first.";
        return;
      }
      const selectedForProposal = Array.from(
        document.querySelectorAll(`.proposal-account-checkbox[data-proposal-id="${CSS.escape(proposalId)}"]:checked:not(:disabled)`)
      ).map((checkbox) => checkbox.dataset.accountId || "").filter(Boolean);
      const filledSelected = selectedForProposal.filter((accountId) => {
        const account = (orderStatus.account_statuses || []).find((item) => item.account_id === accountId);
        return account && ["filled", "partial"].includes(account.status) && account.average_fill_price;
      });
      if (!filledSelected.length) {
        if (status) status.textContent = "None of the checked accounts have a filled entry for this proposal.";
        return;
      }
      const target = firstFilledExitTarget(orderStatus, targetIndex);
      const targetPercent = target ? Number(target.target_percent).toLocaleString(undefined, { maximumFractionDigits: 4 }) : "";
      const orderNote = `${proposalOrderNote(proposal, selectedSignal)} | Exit target ${targetPercent}%`;
      const liveOrderEnabled = currentConfig.execution_mode === "live"
        && Boolean(currentConfig.allow_live_orders)
        && Boolean(currentConfig.trading_enabled);
      let confirmLiveOrder = false;
      if (liveOrderEnabled) {
        const accountLabels = filledSelected.map((accountId) => {
          const account = schwabAccounts.find((item) => item.id === accountId);
          return account ? `${account.account_number || account.id} (${account.label || account.id})` : accountId;
        }).join(", ");
        confirmLiveOrder = window.confirm(
          `Submit LIVE Schwab closing order?\n\n${target?.tos_exit_order_line || "Account-specific SELL order"}\nAccounts: ${accountLabels || "none"}\nNote: ${orderNote}\n\nOnly continue if this is exactly the closing order you want.`
        );
        if (!confirmLiveOrder) {
          if (status) status.textContent = "Closing order cancelled before submission.";
          return;
        }
      }
      button.disabled = true;
      button.textContent = "Sending...";
      if (status) status.textContent = "Sending target exit for filled accounts...";
      try {
        const response = await postJson(
          `/signals/${encodeURIComponent(selectedSignalId)}/proposals/${encodeURIComponent(proposalId)}/targets/${targetIndex}/send`,
          { selected_account_ids: filledSelected, confirm_live_order: confirmLiveOrder, order_note: orderNote }
        );
        exitSendResponses.set(exitSendKey(proposalId, targetIndex), response);
        if (status) status.textContent = sendStatusText(response);
        button.textContent = response.status === "submitted" ? "Sent" : response.status === "dry_run" ? "Prepared" : "Blocked";
        button.classList.toggle("blocked", response.status !== "submitted");
        renderProposalResult(currentProposalResult || { proposals: [], blocked_reasons: [] }, signalById.get(selectedSignalId) || null);
      } catch (error) {
        if (status) status.textContent = `Exit send failed: ${error.message}`;
        button.textContent = "Send failed";
      } finally {
        setTimeout(() => {
          const persisted = exitSendResponses.get(exitSendKey(proposalId, targetIndex));
          const submitted = Boolean(persisted && (persisted.account_results || []).some((item) => item.status === "submitted"));
          const existing = Boolean(persisted && (persisted.account_results || []).some((item) =>
            (item.reasons || []).some((reason) => String(reason).startsWith("target_exit_already_") || String(reason).startsWith("target_exit_status_unverified:"))
          ));
          if (submitted || existing) {
            button.textContent = submitted ? "SELL sent" : "Already sent";
            button.disabled = true;
            button.classList.remove("blocked");
            button.classList.add("sent");
            return;
          }
          button.textContent = "Send SELL to Schwab";
          button.classList.remove("blocked");
          button.disabled = false;
        }, 1800);
      }
    }

    async function sendProposalToSchwab(proposalId, button) {
      if (!proposalId || !selectedSignalId) return;
      const status = document.querySelector(`[data-send-status-for="${CSS.escape(proposalId)}"]`);
      const rawProposal = (currentProposalResult?.proposals || []).find((item) => item.id === proposalId);
      const proposal = rawProposal ? adjustedProposalForQuantity(rawProposal) : null;
      const selectedSignal = signalById.get(selectedSignalId) || null;
      const orderNote = proposalOrderNote(proposal, selectedSignal);
      const selectedForProposal = Array.from(
        document.querySelectorAll(`.proposal-account-checkbox[data-proposal-id="${CSS.escape(proposalId)}"]:checked:not(:disabled)`)
      ).map((checkbox) => checkbox.dataset.accountId || "").filter(Boolean);
      const liveOrderEnabled = currentConfig.execution_mode === "live"
        && Boolean(currentConfig.allow_live_orders)
        && Boolean(currentConfig.trading_enabled);
      let confirmLiveOrder = false;
      if (liveOrderEnabled) {
        const accountLabels = selectedForProposal.map((accountId) => {
          const account = schwabAccounts.find((item) => item.id === accountId);
          return account ? `${account.account_number || account.id} (${account.label || account.id})` : accountId;
        }).join(", ");
        const orderLine = proposal?.tos_order_line || proposalId;
        const maxLoss = proposal?.max_loss == null ? "--" : `$${Number(proposal.max_loss).toFixed(2)}`;
        confirmLiveOrder = window.confirm(
          `Submit LIVE Schwab order?\n\n${orderLine}\nAccounts: ${accountLabels || "none"}\nMax loss: ${maxLoss}\nNote: ${orderNote}\n\nOnly continue if this is exactly the trade you want.`
        );
        if (!confirmLiveOrder) {
          if (status) status.textContent = "Live order cancelled before submission.";
          return;
        }
      }
      button.disabled = true;
      button.textContent = "Sending...";
      if (status) status.textContent = "Checking selected accounts...";
      try {
        const response = await postJson(
          `/signals/${encodeURIComponent(selectedSignalId)}/proposals/${encodeURIComponent(proposalId)}/send`,
          {
            selected_account_ids: selectedForProposal,
            confirm_live_order: confirmLiveOrder,
            quantity: proposal?.quantity || 1,
            limit_price: proposal?.send_limit_price || null,
            order_note: orderNote
          }
        );
        entrySendResponses.set(proposalId, response);
        selectedAccountIds = new Set(response.selected_account_ids || []);
        updateAccountCheckboxes();
        if (status) status.textContent = sendStatusText(response);
        if (response.status === "submitted") {
          await refreshProposalOrderStatus(proposalId, null);
        }
        button.textContent = response.status === "submitted" ? "Sent" : response.status === "dry_run" ? "Prepared" : "Blocked";
        button.classList.toggle("blocked", response.status !== "submitted");
        setTimeout(() => {
          button.textContent = "Send to Schwab";
          button.classList.remove("blocked");
        }, 1800);
      } catch (error) {
        if (status) status.textContent = `Send failed: ${error.message}`;
        button.textContent = "Send failed";
        setTimeout(() => {
          button.textContent = "Send to Schwab";
        }, 1800);
      } finally {
        button.disabled = false;
      }
    }

    function renderProposalResult(result, selectedSignal) {
      currentProposalResult = result || null;
      const proposals = result.proposals || [];
      const reviewButton = document.getElementById("mark-reviewed-button");
      reviewButton.disabled = !selectedSignal || selectedSignal.review_status === "reviewed";
      text("metric-proposals", proposals.length);
      text("proposal-status", proposalReasonHeadline(result.blocked_reasons || []));
      renderProposalGuide(result, selectedSignal);

      const notice = document.getElementById("proposal-notice");
      if (result.preserved_notice) {
        notice.style.display = "block";
        notice.textContent = result.preserved_notice;
      } else if (result.blocked_reasons && result.blocked_reasons.length) {
        notice.style.display = "block";
        notice.textContent = proposalReasonSummary(result.blocked_reasons);
      } else {
        notice.style.display = "none";
        notice.textContent = "";
      }

      renderQuoteFreshness(result);
      renderCandidateDiagnostics(result);

      const list = document.getElementById("proposal-list");
      if (!proposals.length) {
        list.innerHTML = `<div class="empty">No proposal is available for the selected signal</div>`;
        return;
      }

      list.innerHTML = proposals.map((rawProposal, index) => {
        const proposal = adjustedProposalForQuantity(rawProposal);
        const orderNote = proposalOrderNote(proposal, selectedSignal);
        const orderNoteHtml = renderOrderNote(orderNote, proposal.id);
        const legs = (proposal.legs || []).map((leg) => (
          `<div class="leg">${escapeHtml(proposalLegText(leg))}</div>`
        )).join("");
        const tosLine = proposal.tos_order_line
          ? `<div class="tos-head"><div class="label">TOS Format - TOS Order Entry</div><div class="tos-actions"><button class="copy-button copy-tos-button" type="button" data-tos="${escapeHtml(proposal.tos_order_line)}">Copy TOS</button><button class="copy-button send-button send-to-schwab-button" type="button" data-proposal-id="${escapeHtml(proposal.id)}">Send to Schwab</button></div></div><textarea class="tos-line tos-copy-field" readonly rows="1" aria-label="TOS order line">${escapeHtml(proposal.tos_order_line)}</textarea>${orderNoteHtml}`
          : "";
        const entryLimit = proposalEntryLimitText(proposal);
        const exitPlan = renderExitPlan(proposal);
        return `<article class="proposal">
          <div class="proposal-main">
            <div>
              <div class="trade-number">Trade #${index + 1}</div>
              <div class="proposal-title">${escapeHtml(proposalTitle(proposal))}</div>
              <div class="proposal-meta">${escapeHtml(proposalMetaText(proposal, result))}</div>
              ${renderProposalQuantityControl(rawProposal)}
            </div>
            ${proposalExecutionBadge()}
          </div>
          <div class="proposal-facts">
            <div class="proposal-fact"><span class="label">Underlying</span><div class="proposal-fact-value">${escapeHtml(proposalUnderlyingText(proposal, result))}</div></div>
            <div class="proposal-fact"><span class="label">Debit</span><div class="proposal-fact-value">$${Number(proposal.debit || 0).toFixed(2)}</div></div>
            <div class="proposal-fact"><span class="label">Max Loss</span><div class="proposal-fact-value">$${Number(proposal.max_loss || 0).toFixed(2)}</div></div>
          </div>
          ${entryLimit ? `<div class="order-note"><span class="label">Entry Limit</span> ${escapeHtml(entryLimit)}</div>` : ""}
          <div class="legs">${legs}</div>
          ${tosLine}
          ${exitPlan}
          ${renderAccountRouting(proposal)}
        </article>`;
      }).join("");
      attachTosCopyButtons();
    }

    function resultWithPreviousSuccessfulFallback(result, previousResult) {
      const proposals = result?.proposals || [];
      const previousProposals = previousResult?.proposals || [];
      if (
        proposals.length
        || !previousProposals.length
        || !result
        || !previousResult
        || result.signal_id !== previousResult.signal_id
      ) {
        return result;
      }
      const reasons = result.blocked_reasons || [];
      const warning = reasons.length
        ? `No proposal for the selected settings (${proposalReasonSummary(reasons)}); showing the previous successful proposal.`
        : "No proposal for the selected settings; showing the previous successful proposal.";
      return {
        ...previousResult,
        blocked_reasons: ["previous_successful_proposal_preserved", ...reasons],
        candidate_diagnostics: result.candidate_diagnostics || previousResult.candidate_diagnostics,
        chain_contract_count: result.chain_contract_count ?? previousResult.chain_contract_count,
        eligible_contract_count: result.eligible_contract_count ?? previousResult.eligible_contract_count,
        generated_at: result.generated_at || previousResult.generated_at,
        preserved_notice: warning,
        quote_freshness: result.quote_freshness || previousResult.quote_freshness
      };
    }

    function proposalMetaText(proposal, result) {
      const parts = [];
      if ((proposal.reasons || []).includes("itm_primary")) {
        parts.push("ITM");
      } else if ((proposal.reasons || []).includes("atm_primary")) {
        parts.push("ATM");
      }
      parts.push(proposal.structure || "proposal");
      parts.push(`expiry ${proposal.expiry || "--"}`);
      const underlying = proposal.underlying_price ?? result?.underlying_price;
      if (underlying != null) parts.push(`underlying ${Number(underlying).toFixed(2)}`);
      parts.push(`score ${Number(proposal.score || 0).toFixed(2)}`);
      return parts.join(" | ");
    }

    function proposalUnderlyingText(proposal, result) {
      const underlying = proposal?.underlying_price ?? result?.underlying_price;
      if (underlying == null) return "--";
      return Number(underlying).toFixed(2);
    }

    async function loadProposal(signalId, selectedSignal) {
      if (!signalId) {
        renderProposalResult({ proposals: [], blocked_reasons: ["no_signal_selected"] }, null);
        document.getElementById("proposal-refresh-button").disabled = true;
        document.getElementById("mark-reviewed-button").disabled = true;
        return;
      }
      document.getElementById("proposal-refresh-button").disabled = false;
      try {
        const result = await fetchJson(`/signals/${encodeURIComponent(signalId)}/proposals`);
        renderProposalResult(result, selectedSignal || null);
      } catch (error) {
        renderProposalResult({ proposals: [], blocked_reasons: [error.message] }, selectedSignal || null);
      }
    }

    async function refreshSelectedProposal(options = {}) {
      if (!selectedSignalId) return;
      const button = document.getElementById("proposal-refresh-button");
      button.disabled = true;
      text("proposal-status", "refreshing");
      const previousResult = currentProposalResult;
      const previousProposalCount = Number((previousResult?.proposals || []).length);
      try {
        const result = await postJson(`/signals/${encodeURIComponent(selectedSignalId)}/proposals/refresh`);
        const displayResult = resultWithPreviousSuccessfulFallback(result, previousResult);
        let selectedSignal = signalById.get(selectedSignalId) || null;
        renderProposalResult(displayResult, selectedSignal);
        if (displayResult?.preserved_notice) {
          text("proposal-status", "keeping previous proposal");
        }
        if (Array.isArray(options.refreshOrderStatusProposalIds) && options.refreshOrderStatusProposalIds.length) {
          await refreshOrderStatusesForProposalIds(options.refreshOrderStatusProposalIds);
        }
        selectedSignal = await refreshSignalListMetadata({ preserveSelectedSignal: true });
        renderProposalResult(displayResult, selectedSignal || null);
        if (displayResult?.preserved_notice) {
          text("proposal-status", "keeping previous proposal");
        }
        const nextProposalCount = Number((result.proposals || []).length);
        if (nextProposalCount > 0 && nextProposalCount > previousProposalCount) {
          proposalAlertCounts.set(selectedSignalId, nextProposalCount);
          playProposalSound();
        }
      } catch (error) {
        renderProposalResult({ proposals: [], blocked_reasons: [error.message] }, signalById.get(selectedSignalId) || null);
      } finally {
        button.disabled = false;
      }
    }

    async function markSelectedReviewed() {
      if (!selectedSignalId) return;
      const button = document.getElementById("mark-reviewed-button");
      button.disabled = true;
      text("proposal-status", "marking reviewed");
      try {
        const record = await postJson(`/signals/${encodeURIComponent(selectedSignalId)}/review`);
        signalById.set(record.id, record);
        await refreshDashboard();
      } catch (error) {
        renderProposalResult({ proposals: [], blocked_reasons: [error.message] }, signalById.get(selectedSignalId) || null);
        button.disabled = false;
      }
    }

    async function clearSignals() {
      const button = document.getElementById("clear-signals-button");
      const confirmed = window.confirm(
        "Clear all Recent Signals and local persisted signal history? Existing Schwab order audit remains untouched."
      );
      if (!confirmed) return;
      button.disabled = true;
      text("signals-status", "clearing");
      try {
        const result = await deleteJson("/signals");
        selectedSignalId = null;
        userSelectedSignal = false;
        bestProposalSignalId = null;
        signalById = new Map();
        currentProposalResult = null;
        proposalOrderStatuses = new Map();
        entrySendResponses = new Map();
        exitSendResponses = new Map();
        proposalQuantityOverrides = new Map();
        proposalAlertCounts = new Map();
        text("signals-status", `cleared ${result.cleared_count || 0}`);
        await refreshDashboard();
      } catch (error) {
        text("signals-status", `Clear error: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    }

    async function showBestProposalSignal() {
      if (!bestProposalSignalId) return;
      selectedSignalId = bestProposalSignalId;
      userSelectedSignal = false;
      await refreshDashboard();
    }

    function renderSchwabChainCheck(result) {
      const output = document.getElementById("schwab-chain-check-output");
      if (result.status === "received") {
        const sample = result.sample || [];
        const underlying = result.underlying_price == null ? "--" : Number(result.underlying_price).toFixed(2);
        const side = result.contract_type === "PUT" ? "PUT" : "CALL";
        const atmOtmSample = sample
          .filter((contract) => {
            if (result.underlying_price == null) return true;
            const strike = Number(contract.strike || 0);
            return side === "PUT" ? strike <= result.underlying_price : strike >= result.underlying_price;
          })
          .slice(0, 5)
          .map((contract) => `${Number(contract.strike || 0).toFixed(1)}${contract.right === "PUT" ? "P" : "C"}`)
          .join(", ");
        const sampleValue = atmOtmSample || "hidden; use Current Proposal";
        output.innerHTML = `
          <div class="chain-check-note">
            Connectivity only.
            <span>Not a proposal. Use Current Proposal for the actual trade idea and TOS line.</span>
          </div>
          <div class="chain-check-facts">
            <div class="chain-check-fact"><strong>Underlying</strong><span>${escapeHtml(underlying)}</span></div>
            <div class="chain-check-fact"><strong>Expiry</strong><span>${escapeHtml(result.expiry || "--")}</span></div>
            <div class="chain-check-fact"><strong>Contracts</strong><span>${escapeHtml(String(result.contract_count || 0))} ${escapeHtml(result.symbol || "")} ${escapeHtml(side)}</span></div>
            <div class="chain-check-fact"><strong>ATM/OTM Sample</strong><span>${escapeHtml(sampleValue)}</span></div>
          </div>`;
        return;
      }
      if (result.status === "auth_required") {
        output.textContent = `Schwab auth required: ${result.error || "refresh token is not usable"}`;
        return;
      }
      if (result.status === "disabled") {
        output.textContent = "Schwab market data is disabled in this bridge config";
        return;
      }
      if (result.status === "not_configured") {
        output.textContent = "No Schwab token source is configured";
        return;
      }
      output.textContent = result.error || (result.notes || []).join(" ") || "Schwab chain check did not return market data";
    }

    async function checkSchwabChain() {
      const button = document.getElementById("schwab-chain-check-button");
      button.disabled = true;
      const request = schwabChainCheckRequest();
      document.getElementById("schwab-chain-check-output").textContent = `Checking Schwab read-only chain for ${request.label}...`;
      try {
        const expiry = encodeURIComponent(String(dashboardSettings.expiry_label || "1DTE"));
        const symbol = encodeURIComponent(request.symbol);
        const direction = encodeURIComponent(request.direction);
        const result = await fetchJson(`/schwab/option-chain/check?symbol=${symbol}&direction=${direction}&expiry=${expiry}`);
        renderSchwabChainCheck(result);
      } catch (error) {
        document.getElementById("schwab-chain-check-output").textContent = `Schwab chain check error: ${error.message}`;
      } finally {
        button.disabled = false;
      }
    }

    async function createDemoSignal() {
      const button = document.getElementById("demo-signal-button");
      button.disabled = true;
      text("last-update", "Creating demo signal...");
      try {
        const result = await postJson("/demo/signal");
        selectedSignalId = result.id;
        await refreshDashboard();
      } catch (error) {
        text("last-update", `Demo signal error: ${error.message}`);
      } finally {
        button.disabled = false;
      }
    }

    async function refreshDashboard() {
      text("last-update", "Refreshing...");
      try {
        const [health, summary, schwabStatus, accountState, settings, signals] = await Promise.all([
          fetchJson("/health"),
          fetchJson("/dashboard/summary"),
          fetchJson("/schwab/status"),
          fetchJson("/schwab/accounts"),
          fetchJson("/dashboard/settings"),
          fetchJson("/signals?limit=25")
        ]);
        dashboardSettings = settings || dashboardSettings;
        schwabAccounts = accountState.accounts || [];
        schwabAccountNotes = accountState.notes || [];
        selectedAccountIds = new Set(accountState.selected_account_ids || []);
        renderProposalSettingControls();
        renderState(health, summary, schwabStatus);
        const selectedSignal = renderSignals(signals);
        if (selectedSignal && Number(selectedSignal.proposal_count || 0) > 0) {
          setStateValue("state-run", "Proposal Ready", "green");
        }
        await loadProposal(selectedSignalId, selectedSignal);
        text("last-update", `Last update: ${new Date().toLocaleString()}`);
      } catch (error) {
        text("last-update", `Dashboard error: ${error.message}`);
      }
    }

    function optionRefreshWindowParts(now = new Date()) {
      const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: OPTIONS_REFRESH_TIME_ZONE,
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false
      });
      const values = {};
      formatter.formatToParts(now).forEach((part) => {
        if (part.type !== "literal") {
          values[part.type] = part.value;
        }
      });
      return values;
    }

    function isOptionsRefreshWindow(now = new Date()) {
      const parts = optionRefreshWindowParts(now);
      if (parts.weekday === "Sat" || parts.weekday === "Sun") return false;
      const hour = Number(parts.hour);
      const minute = Number(parts.minute);
      if (!Number.isFinite(hour) || !Number.isFinite(minute)) return false;
      const minutes = hour * 60 + minute;
      return minutes >= (9 * 60 + 30) && minutes <= (16 * 60 + 15);
    }

    function dashboardRefreshIntervalMs(now = new Date()) {
      return isOptionsRefreshWindow(now) ? OPTIONS_REFRESH_ACTIVE_MS : OPTIONS_REFRESH_IDLE_MS;
    }

    function scheduleDashboardRefresh() {
      if (dashboardRefreshTimer) {
        clearTimeout(dashboardRefreshTimer);
      }
      dashboardRefreshTimer = setTimeout(async () => {
        await refreshDashboard();
        scheduleDashboardRefresh();
      }, dashboardRefreshIntervalMs());
    }

    document.getElementById("refresh-button").addEventListener("click", refreshDashboard);
    document.getElementById("show-proposal-button").addEventListener("click", showBestProposalSignal);
    document.getElementById("proposal-refresh-button").addEventListener("click", refreshSelectedProposal);
    document.getElementById("mark-reviewed-button").addEventListener("click", markSelectedReviewed);
    document.getElementById("clear-signals-button").addEventListener("click", clearSignals);
    document.getElementById("schwab-chain-check-button").addEventListener("click", checkSchwabChain);
    document.getElementById("demo-signal-button").addEventListener("click", createDemoSignal);
    document.getElementById("sound-toggle-button").addEventListener("click", toggleProposalSound);
    document.getElementById("sound-test-button").addEventListener("click", testProposalSound);
    document.getElementById("expiry-buttons").addEventListener("click", (event) => {
      const button = event.target.closest("[data-expiry-label]");
      if (!button) return;
      setProposalExpiry(button.dataset.expiryLabel);
    });
    document.getElementById("allow-itm-checkbox").addEventListener("change", (event) => {
      setProposalAllowItm(event.target.checked);
    });
    document.getElementById("max-loss-buttons").addEventListener("click", (event) => {
      const button = event.target.closest("[data-max-loss]");
      if (!button) return;
      setProposalMaxLoss(button.dataset.maxLoss);
    });
    document.getElementById("entry-offset-buttons").addEventListener("click", (event) => {
      const button = event.target.closest("[data-entry-offset]");
      if (!button) return;
      setProposalEntryOffset(button.dataset.entryOffset);
    });
    document.getElementById("target-percent-controls").addEventListener("click", (event) => {
      const button = event.target.closest("[data-target-apply]");
      if (!button) return;
      setProposalTargets(readTargetPercentages());
    });
    document.getElementById("target-percent-controls").addEventListener("input", () => {
      captureTargetDraftValues();
      text("proposal-status", "targets edited; click Apply");
    });
    document.getElementById("target-percent-controls").addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      setProposalTargets(readTargetPercentages());
    });
    warmSpeechVoices();
    document.addEventListener("pointerdown", () => unlockProposalSound(false), { passive: true });
    document.addEventListener("keydown", () => unlockProposalSound(false));
    updateSoundControls();
    refreshDashboard();
    scheduleDashboardRefresh();
  </script>
</body>
</html>"""
