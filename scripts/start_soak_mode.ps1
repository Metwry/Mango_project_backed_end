param(
    [string]$ProjectRoot = "C:\Users\13647\Desktop\WRY\Code\My_Project\Back_end_project\mango_project",
    [string]$LogDir = "tmp_stress_logs",
    [int]$MarketSyncSeconds = 5,
    [int]$CaptureSeconds = 7,
    [int]$AggH4Seconds = 13,
    [int]$AggD1Seconds = 17,
    [int]$AggMon1Seconds = 19,
    [int]$CleanupSeconds = 23
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$resolvedLogDir = Join-Path $resolvedRoot $LogDir
if (!(Test-Path $resolvedLogDir)) {
    New-Item -ItemType Directory -Path $resolvedLogDir | Out-Null
}

$commonEnv = @"
`$env:MARKET_QUOTE_PROVIDER='fake'
`$env:MARKET_SYNC_TEST_EVERY_SECONDS='$MarketSyncSeconds'
`$env:SNAPSHOT_CAPTURE_TEST_EVERY_SECONDS='$CaptureSeconds'
`$env:SNAPSHOT_AGG_H4_TEST_EVERY_SECONDS='$AggH4Seconds'
`$env:SNAPSHOT_AGG_D1_TEST_EVERY_SECONDS='$AggD1Seconds'
`$env:SNAPSHOT_AGG_MON1_TEST_EVERY_SECONDS='$AggMon1Seconds'
`$env:SNAPSHOT_CLEANUP_TEST_EVERY_SECONDS='$CleanupSeconds'
cd '$resolvedRoot'
"@

function Start-SoakProc([string]$name, [string]$command, [string]$logFile) {
    $full = $commonEnv + "`n" + $command + " *> '$logFile'"
    return Start-Process pwsh -ArgumentList @("-NoProfile", "-Command", $full) -PassThru
}

$beat = Start-SoakProc -name "beat" -command "celery -A mango_project beat -l info" -logFile (Join-Path $resolvedLogDir "beat.log")
$market = Start-SoakProc -name "market_sync" -command "celery -A mango_project worker -n market_sync@%h -Q market_sync -l info -P solo" -logFile (Join-Path $resolvedLogDir "market_sync.log")
$capture = Start-SoakProc -name "snapshot_capture" -command "celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info -P solo" -logFile (Join-Path $resolvedLogDir "snapshot_capture.log")
$agg = Start-SoakProc -name "snapshot_aggregate" -command "celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info -P solo" -logFile (Join-Path $resolvedLogDir "snapshot_aggregate.log")
$cleanup = Start-SoakProc -name "snapshot_cleanup" -command "celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info -P solo" -logFile (Join-Path $resolvedLogDir "snapshot_cleanup.log")

$pidFile = Join-Path $resolvedLogDir "soak_pids.txt"
@(
    $beat.Id
    $market.Id
    $capture.Id
    $agg.Id
    $cleanup.Id
) | Set-Content -Path $pidFile -Encoding utf8

Write-Host "Soak mode started."
Write-Host "PIDs saved to: $pidFile"
Write-Host "Logs directory: $resolvedLogDir"
Write-Host "Tail examples:"
Write-Host "  Get-Content '$resolvedLogDir\beat.log' -Wait"
Write-Host "  Get-Content '$resolvedLogDir\market_sync.log' -Wait"
