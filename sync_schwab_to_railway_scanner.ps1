[CmdletBinding()]
param(
    [string]$TokenFilePath = "D:\data\schwab\schwab_tokens.json",
    [string]$RailwayService = "schwab-market-scanner",
    [string]$RailwayEnvironment = "production",
    [string]$RailwayCli = "railway",
    [switch]$SkipRedeploy,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Railway([string]$RailwayCliCommand, [string[]]$Args) {
    $output = & $RailwayCliCommand @Args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$RailwayCliCommand $($Args -join ' ') failed:`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function Set-RailwayVariable([string]$RailwayCliCommand, [string[]]$CommonArgs, [string]$Key, [string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "Refusing to set empty Railway variable $Key."
    }
    $args = @('variable', 'set') + $CommonArgs + @($Key, '--stdin')
    $output = [string]$Value | & $RailwayCliCommand @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "$RailwayCliCommand $($args -join ' ') failed:`n$($output -join [Environment]::NewLine)"
    }
}

if (-not (Test-Path -LiteralPath $TokenFilePath)) {
    throw "Token file not found: $TokenFilePath. Refresh Schwab through the CLEAN integration first."
}

$token = Get-Content -LiteralPath $TokenFilePath -Raw | ConvertFrom-Json
foreach ($field in @('access_token', 'refresh_token', 'access_token_expires_at')) {
    if (-not $token.PSObject.Properties.Name.Contains($field) -or [string]::IsNullOrWhiteSpace([string]$token.$field)) {
        throw "Token file $TokenFilePath is missing required field $field."
    }
}

$tokenPath = "/data/schwab/schwab_tokens_$(Get-Date -Format yyyyMMdd_HHmmss).json"
$commonArgs = @('-s', $RailwayService, '-e', $RailwayEnvironment)

if ($DryRun) {
    [pscustomobject]@{
        token_file = $TokenFilePath
        railway_service = $RailwayService
        railway_environment = $RailwayEnvironment
        schwab_access_token_expires_at = [string]$token.access_token_expires_at
        would_set = @{
            SCHWAB_ACCESS_TOKEN = "<redacted>"
            SCHWAB_REFRESH_TOKEN = "<redacted>"
            SCHWAB_ACCESS_TOKEN_EXPIRES_AT = [string]$token.access_token_expires_at
            SCHWAB_TOKEN_STORE_PATH = $tokenPath
        }
    } | ConvertTo-Json -Depth 5
    exit 0
}

if (-not (Get-Command $RailwayCli -ErrorAction SilentlyContinue)) {
    throw "Railway CLI is not installed or not on PATH."
}

Write-Step "Updating Railway Schwab token variables for $RailwayService/$RailwayEnvironment"
Set-RailwayVariable -RailwayCliCommand $RailwayCli -CommonArgs $commonArgs -Key 'SCHWAB_ACCESS_TOKEN' -Value ([string]$token.access_token)
Set-RailwayVariable -RailwayCliCommand $RailwayCli -CommonArgs $commonArgs -Key 'SCHWAB_REFRESH_TOKEN' -Value ([string]$token.refresh_token)
Set-RailwayVariable -RailwayCliCommand $RailwayCli -CommonArgs $commonArgs -Key 'SCHWAB_ACCESS_TOKEN_EXPIRES_AT' -Value ([string]$token.access_token_expires_at)
Set-RailwayVariable -RailwayCliCommand $RailwayCli -CommonArgs $commonArgs -Key 'SCHWAB_TOKEN_STORE_PATH' -Value $tokenPath

if (-not $SkipRedeploy) {
    Write-Step "Redeploying Railway service"
    Invoke-Railway -RailwayCliCommand $RailwayCli -Args (@('redeploy') + $commonArgs + @('-y')) | Out-Null
}

Write-Step "Scanner Railway token sync completed"
