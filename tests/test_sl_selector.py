# ============================================================================
# File:          test_sl_selector.py
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
# Purpose:       Phase-2 look&feel parity — the SL% selector must be present in
#                the rendered dashboard AND the send path must forward the chosen
#                stop_loss_percent to the OTOCO builder (it previously defaulted to
#                a constant and was never sent from the UI).
# ============================================================================
import market_scanner.dashboard as dashboard


def _html():
    return dashboard.dashboard_html("TEST_KEY")


def test_sl_selector_control_present():
    html = _html()
    assert 'id="stop-loss-buttons"' in html          # settings-bar control
    assert "stopLossChoices" in html                  # client default choice list
    assert "function setStopLoss(" in html            # handler wired


def test_send_forwards_stop_loss_percent():
    html = _html()
    # the main send URL must carry the durable SL% (was target_percentages only)
    assert "stop_loss_percent=${encodeURIComponent(slPct)}" in html


def test_default_sl_is_fifty():
    html = _html()
    assert "stopLossPercent: 50" in html
