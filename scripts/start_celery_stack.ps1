param(
    [string]$ProjectRoot = "",
    [string]$EnvName = "Back_end_project",
    [string[]]$Targets = @("all"),
    [switch]$WithBeat,
    [string]$Pool = "solo",
    [string]$LogDir = "tmp_celery_logs",
    [switch]$FollowLogs,
    [int]$TailLines = 50,
    [switch]$FakeProvider,
    [int]$MarketSyncEverySeconds = 0,
    [int]$SnapshotCaptureEverySeconds = 0,
    [int]$SnapshotAggH4EverySeconds = 0,
    [int]$SnapshotAggD1EverySeconds = 0,
    [int]$SnapshotAggMon1EverySeconds = 0,
    [int]$SnapshotCleanupEverySeconds = 0
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$resolvedLogDir = Join-Path $ProjectRoot $LogDir
if (!(Test-Path $resolvedLogDir)) {
    New-Item -ItemType Directory -Path $resolvedLogDir | Out-Null
}

function Normalize-Targets([string[]]$rawTargets) {
    $out = New-Object System.Collections.Generic.HashSet[string]
    foreach ($raw in $rawTargets) {
        $t = [string]$raw
        if ([string]::IsNullOrWhiteSpace($t)) { continue }
        $v = $t.Trim().ToLowerInvariant()
        switch ($v) {
            "all" {
                [void]$out.Add("market_sync")
                [void]$out.Add("snapshot_capture")
                [void]$out.Add("snapshot_aggregate")
                [void]$out.Add("snapshot_cleanup")
                continue
            }
            "market" { [void]$out.Add("market_sync"); continue }
            "market_sync" { [void]$out.Add("market_sync"); continue }
            "snapshot" {
                [void]$out.Add("snapshot_capture")
                [void]$out.Add("snapshot_aggregate")
                [void]$out.Add("snapshot_cleanup")
                continue
            }
            "snapshot_capture" { [void]$out.Add("snapshot_capture"); continue }
            "snapshot_aggregate" { [void]$out.Add("snapshot_aggregate"); continue }
            "snapshot_cleanup" { [void]$out.Add("snapshot_cleanup"); continue }
            default { throw "Unknown target: $t. Allowed: all, market_sync, snapshot_capture, snapshot_aggregate, snapshot_cleanup, market, snapshot" }
        }
    }
    return @($out)
}

$targetWorkers = Normalize-Targets $Targets

$commonEnv = @"
cd '$ProjectRoot'
"@

if ($FakeProvider) {
    $commonEnv += @"
`$env:MARKET_QUOTE_PROVIDER='fake'
"@
}

if ($MarketSyncEverySeconds -gt 0) {
    $commonEnv += @"
`$env:MARKET_SYNC_TEST_EVERY_SECONDS='$MarketSyncEverySeconds'
"@
}
if ($SnapshotCaptureEverySeconds -gt 0) {
    $commonEnv += @"
`$env:SNAPSHOT_CAPTURE_TEST_EVERY_SECONDS='$SnapshotCaptureEverySeconds'
"@
}
if ($SnapshotAggH4EverySeconds -gt 0) {
    $commonEnv += @"
`$env:SNAPSHOT_AGG_H4_TEST_EVERY_SECONDS='$SnapshotAggH4EverySeconds'
"@
}
if ($SnapshotAggD1EverySeconds -gt 0) {
    $commonEnv += @"
`$env:SNAPSHOT_AGG_D1_TEST_EVERY_SECONDS='$SnapshotAggD1EverySeconds'
"@
}
if ($SnapshotAggMon1EverySeconds -gt 0) {
    $commonEnv += @"
`$env:SNAPSHOT_AGG_MON1_TEST_EVERY_SECONDS='$SnapshotAggMon1EverySeconds'
"@
}
if ($SnapshotCleanupEverySeconds -gt 0) {
    $commonEnv += @"
`$env:SNAPSHOT_CLEANUP_TEST_EVERY_SECONDS='$SnapshotCleanupEverySeconds'
"@
}

function Start-StackProcess([string]$name, [string]$command, [string]$logPath) {
    $script = $commonEnv + "`n" + "conda run --no-capture-output -n $EnvName $command *> '$logPath'"
    return Start-Process pwsh -ArgumentList @("-NoProfile", "-Command", $script) -PassThru
}

$commands = @{
    "market_sync" = "celery -A mango_project worker -n market_sync@%h -Q market_sync -l info -P $Pool"
    "snapshot_capture" = "celery -A mango_project worker -n snapshot_capture@%h -Q snapshot_capture -l info -P $Pool"
    "snapshot_aggregate" = "celery -A mango_project worker -n snapshot_aggregate@%h -Q snapshot_aggregate -l info -P $Pool"
    "snapshot_cleanup" = "celery -A mango_project worker -n snapshot_cleanup@%h -Q snapshot_cleanup -l info -P $Pool"
}

$records = @()
if ($WithBeat) {
    $beatLog = Join-Path $resolvedLogDir "beat.log"
    $beatProc = Start-StackProcess -name "beat" -command "celery -A mango_project beat -l info" -logPath $beatLog
    $records += [PSCustomObject]@{ Name = "beat"; Pid = $beatProc.Id; Log = $beatLog }
}

foreach ($name in $targetWorkers) {
    $cmd = $commands[$name]
    $log = Join-Path $resolvedLogDir "$name.log"
    $proc = Start-StackProcess -name $name -command $cmd -logPath $log
    $records += [PSCustomObject]@{ Name = $name; Pid = $proc.Id; Log = $log }
}

$pidFile = Join-Path $resolvedLogDir "stack_pids.csv"
"name,pid,log" | Set-Content -Path $pidFile -Encoding utf8
foreach ($r in $records) {
    "$($r.Name),$($r.Pid),$($r.Log)" | Add-Content -Path $pidFile -Encoding utf8
}

Write-Host "Started celery stack."
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Conda Env: $EnvName"
Write-Host "LogDir: $resolvedLogDir"
Write-Host "PID file: $pidFile"
Write-Host "Processes:"
$records | Format-Table -AutoSize

Start-Sleep -Milliseconds 800
$exited = @()
foreach ($r in $records) {
    try {
        Get-Process -Id $r.Pid -ErrorAction Stop | Out-Null
    }
    catch {
        $exited += $r
    }
}

if ($exited.Count -gt 0) {
    Write-Warning "Some processes exited immediately. Showing last 40 log lines:"
    foreach ($r in $exited) {
        Write-Host ""
        Write-Host ("--- " + $r.Name + " (" + $r.Log + ") ---")
        if (Test-Path $r.Log) {
            Get-Content $r.Log -Tail 40
        } else {
            Write-Host "log file not found"
        }
    }
}

Write-Host ""
Write-Host "Log tail examples:"
foreach ($r in $records) {
    Write-Host ("  Get-Content '" + $r.Log + "' -Wait")
}

if ($FollowLogs) {
    $paths = @($records | ForEach-Object { $_.Log })
    if ($paths.Count -gt 0) {
        $tail = [Math]::Max(1, $TailLines)
        Write-Host ""
        Write-Host "Following logs (Ctrl + C to stop):"
        Get-Content -Path $paths -Tail $tail -Wait
    }
}
