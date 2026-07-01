# ============================================================================
# File:          setup_dashboard_auth.ps1
# Project:       Schwab Market Scanner
# Created:       2026-07-01 (EST) · Author: Claude (Anthropic) + Raghu
# Purpose:       One-shot: set each trader's password, generate a session secret,
#                and print the values to paste into Railway. Passwords are typed
#                locally (getpass), hashed, and written to a gitignored file.
# ============================================================================
$ErrorActionPreference = "Stop"
$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$root   = Split-Path -Parent $here                 # scripts\ -> scanner repo root
Set-Location $root

Write-Host ""
Write-Host "==== STEP 1 of 3: set each trader's password ====" -ForegroundColor Cyan
python scripts/manage_users.py set raghu --name "Raghu"
python scripts/manage_users.py set vara  --name "Vara"
python scripts/manage_users.py set dhanu --name "Dhanu"

Write-Host ""
Write-Host "==== STEP 2 of 3: copy your Railway values ====" -ForegroundColor Cyan
Write-Host "DASHBOARD_AUTH_ENABLED =" -ForegroundColor Yellow
Write-Host "  true"
$secret = python -c "import secrets; print(secrets.token_urlsafe(48))"
Write-Host "DASHBOARD_SESSION_SECRET =" -ForegroundColor Yellow
Write-Host ("  " + $secret)
Write-Host "DASHBOARD_USERS_JSON =" -ForegroundColor Yellow
$blob = python scripts/manage_users.py print-env
Write-Host ("  " + $blob)

Write-Host ""
Write-Host "==== STEP 3 of 3: paste into Railway (schwab-market-scanner) ====" -ForegroundColor Cyan
Write-Host "Service -> Variables: add the three above, then Deploy."
Write-Host "Machine callers keep working via the existing SCANNER_API_KEY / GPT_ACTION_API_KEY (X-API-Key bypass)."
Write-Host "After redeploy, open the dashboard URL -> you get a login page."
