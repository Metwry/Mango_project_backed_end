param(
    [string]$ProjectRoot = "",
    [string]$LogDir = "tmp_celery_logs"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$resolvedLogDir = Join-Path $ProjectRoot $LogDir
$pidFile = Join-Path $resolvedLogDir "stack_pids.csv"
$stopped = New-Object System.Collections.Generic.HashSet[int]

function Stop-IfRunning([int]$TargetPid, [string]$Label) {
    if ($TargetPid -le 0) {
        return
    }
    if ($stopped.Contains($TargetPid)) {
        return
    }
    try {
        Stop-Process -Id $TargetPid -Force -ErrorAction Stop
        [void]$stopped.Add($TargetPid)
        Write-Host "Stopped $Label (PID=$TargetPid)"
    }
    catch {
        Write-Host "Already stopped $Label (PID=$TargetPid)"
    }
}

if (Test-Path $pidFile) {
    $lines = Get-Content $pidFile | Where-Object { $_ -and $_ -notmatch "^name,pid,log$" }
    foreach ($line in $lines) {
        $parts = $line.Split(",", 3)
        if ($parts.Length -lt 2) {
            continue
        }
        $name = $parts[0]
        $pidText = $parts[1]
        if ($pidText -match "^\d+$") {
            Stop-IfRunning -TargetPid ([int]$pidText) -Label $name
        }
    }

    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$self = $PID
$fallback = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $self -and
    $_.CommandLine -and
    $_.CommandLine -match "mango_project" -and
    $_.CommandLine -match "celery"
}

foreach ($proc in $fallback) {
    Stop-IfRunning -TargetPid ([int]$proc.ProcessId) -Label $proc.Name
}

Write-Host "Done."
