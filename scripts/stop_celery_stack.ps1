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

if (!(Test-Path $pidFile)) {
    Write-Host "PID file not found: $pidFile"
    Write-Host "Fallback scan: try stopping celery processes for mango_project..."
    $fallback = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine -match "celery" -and $_.CommandLine -match "mango_project"
    }
    if (!$fallback) {
        Write-Host "No matching celery processes found."
        exit 0
    }
    foreach ($p in $fallback) {
        $targetPid = [int]$p.ProcessId
        try {
            Stop-Process -Id $targetPid -Force -ErrorAction Stop
            Write-Host "Stopped PID $targetPid via fallback scan"
        }
        catch {
            Write-Host "Already stopped PID $targetPid via fallback scan"
        }
    }
    Write-Host "Done (fallback scan)."
    exit 0
}

$lines = Get-Content $pidFile | Where-Object { $_ -and $_ -notmatch "^name,pid,log$" }
foreach ($line in $lines) {
    $parts = $line.Split(",", 3)
    if ($parts.Length -lt 2) { continue }
    $name = $parts[0]
    $pidText = $parts[1]
    if ($pidText -notmatch "^\d+$") { continue }
    $targetPid = [int]$pidText
    try {
        $proc = Get-Process -Id $targetPid -ErrorAction Stop
        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        Write-Host "Stopped $name (PID=$targetPid)"
    }
    catch {
        Write-Host "Already stopped $name (PID=$targetPid)"
    }
}

Remove-Item $pidFile -Force
Write-Host "Done."
