param(
    [string]$ProjectRoot = "",
    [string]$EnvName = "Back_end_project",
    [string[]]$Targets = @("all"),
    [switch]$WithBeat,
    [string]$Pool = "threads",
    [int]$Concurrency = 4,
    [string]$LogDir = "resource/tmp_celery_logs",
    [string]$StateDir = "resource/tmp_celery_state",
    [switch]$FollowLogs,
    [int]$TailLines = 50,
    [switch]$FakeProvider
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$resolvedLogDir = Join-Path $ProjectRoot $LogDir
if (!(Test-Path $resolvedLogDir)) {
    New-Item -ItemType Directory -Path $resolvedLogDir | Out-Null
}

$resolvedStateDir = Join-Path $ProjectRoot $StateDir
if (!(Test-Path $resolvedStateDir)) {
    New-Item -ItemType Directory -Path $resolvedStateDir | Out-Null
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

function Quote-PS([string]$value) {
    return "'" + ($value -replace "'", "''") + "'"
}

function Resolve-CondaPython([string]$envName) {
    if (Test-Path $envName) {
        $candidate = Join-Path (Resolve-Path $envName).Path "python.exe"
        if (Test-Path $candidate) {
            return $candidate
        }
    }

    $condaCmd = Get-Command conda -ErrorAction SilentlyContinue
    if (!$condaCmd) {
        throw "Could not find 'conda' on PATH. Pass -EnvName with a conda env path or add conda to PATH."
    }

    $envList = & $condaCmd.Source env list --json | ConvertFrom-Json
    foreach ($envPath in $envList.envs) {
        $isExactPath = $envPath -ieq $envName
        $isNameMatch = (Split-Path $envPath -Leaf) -ieq $envName
        if ($isExactPath -or $isNameMatch) {
            $pythonPath = Join-Path $envPath "python.exe"
            if (Test-Path $pythonPath) {
                return $pythonPath
            }
        }
    }

    throw "Could not resolve python.exe for conda env '$envName'."
}

function Start-CeleryProcess(
    [string]$Name,
    [string[]]$CeleryArgs,
    [string]$PythonPath,
    [string]$ProjectDir,
    [string]$LogPath,
    [hashtable]$ProcessEnv
) {
    $lines = @(
        '$ErrorActionPreference = ''Stop'''
        ("Set-Location " + (Quote-PS $ProjectDir))
    )

    foreach ($key in $ProcessEnv.Keys) {
        $lines += ('$env:' + $key + '=' + (Quote-PS ([string]$ProcessEnv[$key])))
    }

    $quotedArgs = @((Quote-PS $PythonPath), "-m", "celery")
    foreach ($arg in $CeleryArgs) {
        $quotedArgs += (Quote-PS $arg)
    }

    $lines += ("& " + ($quotedArgs -join " ") + " *> " + (Quote-PS $LogPath))
    $script = $lines -join "`n"

    return Start-Process pwsh -ArgumentList @("-NoProfile", "-Command", $script) -PassThru
}

$targetWorkers = Normalize-Targets $Targets
$pythonPath = Resolve-CondaPython $EnvName

$commands = @{
    "market_sync" = @("-A", "mango_project", "worker", "-n", "market_sync@%h", "-Q", "market_sync", "-l", "info", "-P", $Pool, "--concurrency", "$Concurrency")
    "snapshot_capture" = @("-A", "mango_project", "worker", "-n", "snapshot_capture@%h", "-Q", "snapshot_capture", "-l", "info", "-P", $Pool, "--concurrency", "$Concurrency")
    "snapshot_aggregate" = @("-A", "mango_project", "worker", "-n", "snapshot_aggregate@%h", "-Q", "snapshot_aggregate", "-l", "info", "-P", $Pool, "--concurrency", "$Concurrency")
    "snapshot_cleanup" = @("-A", "mango_project", "worker", "-n", "snapshot_cleanup@%h", "-Q", "snapshot_cleanup", "-l", "info", "-P", $Pool, "--concurrency", "$Concurrency")
}

$processEnv = @{}
if ($FakeProvider) {
    $processEnv["MARKET_QUOTE_PROVIDER"] = "fake"
}

$records = @()
if ($WithBeat) {
    $beatLog = Join-Path $resolvedLogDir "beat.log"
    $beatSchedule = Join-Path $resolvedStateDir "celerybeat-schedule"
    $beatProc = Start-CeleryProcess -Name "beat" -CeleryArgs @("-A", "mango_project", "beat", "-l", "info", "--schedule", $beatSchedule) -PythonPath $pythonPath -ProjectDir $ProjectRoot -LogPath $beatLog -ProcessEnv $processEnv
    $records += [PSCustomObject]@{ Name = "beat"; Pid = $beatProc.Id; Log = $beatLog }
}

foreach ($name in $targetWorkers) {
    $log = Join-Path $resolvedLogDir "$name.log"
    $proc = Start-CeleryProcess -Name $name -CeleryArgs $commands[$name] -PythonPath $pythonPath -ProjectDir $ProjectRoot -LogPath $log -ProcessEnv $processEnv
    $records += [PSCustomObject]@{ Name = $name; Pid = $proc.Id; Log = $log }
}

$pidFile = Join-Path $resolvedLogDir "stack_pids.csv"
"name,pid,log" | Set-Content -Path $pidFile -Encoding utf8
foreach ($r in $records) {
    "$($r.Name),$($r.Pid),$($r.Log)" | Add-Content -Path $pidFile -Encoding utf8
}

Write-Host "Started celery stack."
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Python: $pythonPath"
Write-Host "LogDir: $resolvedLogDir"
Write-Host "StateDir: $resolvedStateDir"
Write-Host "PID file: $pidFile"
Write-Host "Processes:"
$records | Format-Table -AutoSize

Start-Sleep -Milliseconds 1000
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
