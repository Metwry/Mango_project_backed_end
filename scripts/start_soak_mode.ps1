param(
    [string]$ProjectRoot = "",
    [string]$EnvName = "Back_end_project",
    [string]$LogDir = "tmp_stress_logs",
    [int]$MarketSyncSeconds = 5,
    [int]$CaptureSeconds = 7,
    [int]$AggH4Seconds = 13,
    [int]$AggD1Seconds = 17,
    [int]$AggMon1Seconds = 19,
    [int]$CleanupSeconds = 23
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$startScript = Join-Path $PSScriptRoot "start_celery.ps1"
& powershell -ExecutionPolicy Bypass -File $startScript `
    -ProjectRoot $ProjectRoot `
    -EnvName $EnvName `
    -Targets all `
    -WithBeat `
    -Pool solo `
    -LogDir $LogDir `
    -FakeProvider `
    -MarketSyncEverySeconds $MarketSyncSeconds `
    -SnapshotCaptureEverySeconds $CaptureSeconds `
    -SnapshotAggH4EverySeconds $AggH4Seconds `
    -SnapshotAggD1EverySeconds $AggD1Seconds `
    -SnapshotAggMon1EverySeconds $AggMon1Seconds `
    -SnapshotCleanupEverySeconds $CleanupSeconds

if ($LASTEXITCODE -ne 0) {
    throw "Failed to start soak mode via scripts/start_celery.ps1"
}
