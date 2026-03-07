param(
    [string]$EnvName = "Back_end_project",
    [string]$ProjectRoot = "",
    [string]$StartDate = "",
    [string]$EndDate = "",
    [string[]]$SyncMarkets = @("cn", "hk", "us", "fx", "crypto"),
    [string[]]$CalendarMarkets = @("US", "CN", "HK"),
    [string]$CalendarOutDir = "",
    [string[]]$LogoMarkets = @("us", "hk", "crypto"),
    [switch]$SkipMigrate,
    [switch]$SkipSymbols,
    [switch]$SkipCalendar,
    [switch]$WithLogoSync,
    [switch]$SymbolsInsertOnly
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

if ([string]::IsNullOrWhiteSpace($StartDate)) {
    $year = (Get-Date).Year
    $StartDate = "{0}-01-01" -f $year
}
if ([string]::IsNullOrWhiteSpace($EndDate)) {
    $year = (Get-Date).Year + 1
    $EndDate = "{0}-12-31" -f $year
}

Set-Location $ProjectRoot

function Invoke-CondaPython([string[]]$PyArgs) {
    & conda run -n $EnvName python @PyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: conda run -n $EnvName python $($PyArgs -join ' ')"
    }
}

Write-Host "Bootstrap project first run"
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Conda Env: $EnvName"
Write-Host "Calendar Range: $StartDate -> $EndDate"

if (-not $SkipMigrate) {
    Write-Host "`n[1/4] Running migrations..."
    Invoke-CondaPython @("manage.py", "migrate")
}

if (-not $SkipSymbols) {
    Write-Host "`n[2/4] Syncing symbols..."
    $args = @("manage.py", "sync_symbols", "--markets")
    $args += $SyncMarkets
    if ($SymbolsInsertOnly) {
        $args += "--insert-only"
    }
    Invoke-CondaPython $args
}

if (-not $SkipCalendar) {
    Write-Host "`n[3/4] Building market calendar CSV..."
    $args = @(
        "manage.py",
        "build_market_calendar_csv",
        "--start", $StartDate,
        "--end", $EndDate,
        "--markets"
    )
    $args += $CalendarMarkets
    if (-not [string]::IsNullOrWhiteSpace($CalendarOutDir)) {
        $args += @("--out-dir", $CalendarOutDir)
    }
    Invoke-CondaPython $args
}

if ($WithLogoSync) {
    Write-Host "`n[4/4] Syncing logo metadata..."
    $args = @("manage.py", "sync_logo_data", "--markets")
    $args += $LogoMarkets
    Invoke-CondaPython $args
} else {
    Write-Host "`n[4/4] Skip logo sync (use -WithLogoSync to enable)"
}

Write-Host "`nFirst-run bootstrap completed."
