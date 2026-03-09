param(
    [string]$ProjectRoot = "",
    [string]$LogDir = "tmp_stress_logs"
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$stopScript = Join-Path $PSScriptRoot "stop_celery.ps1"
& powershell -ExecutionPolicy Bypass -File $stopScript -ProjectRoot $ProjectRoot -LogDir $LogDir

if ($LASTEXITCODE -ne 0) {
    throw "Failed to stop soak mode via scripts/stop_celery.ps1"
}
