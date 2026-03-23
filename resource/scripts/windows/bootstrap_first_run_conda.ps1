param(
    [string]$EnvName = "Back_end_project",
    [string]$ProjectRoot = "",
    [string[]]$SyncMarkets = @("cn", "hk", "us", "fx", "crypto"),
    [string[]]$LogoMarkets = @("us", "hk", "crypto"),
    [switch]$SkipMigrate,
    [switch]$SkipSymbols,
    [switch]$WithLogoSync,
    [switch]$SymbolsInsertOnly
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..\\..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
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

if (-not $SkipMigrate) {
    Write-Host "`n[1/3] Running migrations..."
    Invoke-CondaPython @("manage.py", "migrate")
}

if (-not $SkipSymbols) {
    Write-Host "`n[2/3] Syncing symbols..."
    $args = @("manage.py", "sync_symbols", "--markets")
    $args += $SyncMarkets
    if ($SymbolsInsertOnly) {
        $args += "--insert-only"
    }
    Invoke-CondaPython $args
}

if ($WithLogoSync) {
    Write-Host "`n[3/3] Syncing logo metadata..."
    $args = @("manage.py", "sync_logo_data", "--markets")
    $args += $LogoMarkets
    Invoke-CondaPython $args
} else {
    Write-Host "`n[3/3] Skip logo sync (use -WithLogoSync to enable)"
}

Write-Host "`nFirst-run bootstrap completed."
