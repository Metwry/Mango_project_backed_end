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
    exit 0
}

$lines = Get-Content $pidFile | Where-Object { $_ -and $_ -notmatch "^name,pid,log$" }
foreach ($line in $lines) {
    $parts = $line.Split(",", 3)
    if ($parts.Length -lt 2) { continue }
    $name = $parts[0]
    $pidText = $parts[1]
    if ($pidText -notmatch "^\d+$") { continue }
    $pid = [int]$pidText
    try {
        $proc = Get-Process -Id $pid -ErrorAction Stop
        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        Write-Host "Stopped $name (PID=$pid)"
    }
    catch {
        Write-Host "Already stopped $name (PID=$pid)"
    }
}

Remove-Item $pidFile -Force
Write-Host "Done."

