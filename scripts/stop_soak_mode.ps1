param(
    [string]$ProjectRoot = "C:\Users\13647\Desktop\WRY\Code\My_Project\Back_end_project\mango_project",
    [string]$LogDir = "tmp_stress_logs"
)

$ErrorActionPreference = "Stop"
$resolvedRoot = (Resolve-Path $ProjectRoot).Path
$resolvedLogDir = Join-Path $resolvedRoot $LogDir
$pidFile = Join-Path $resolvedLogDir "soak_pids.txt"

if (!(Test-Path $pidFile)) {
    Write-Host "PID file not found: $pidFile"
    exit 0
}

$pids = Get-Content $pidFile | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^\d+$' }
foreach ($pid in $pids) {
    try {
        $proc = Get-Process -Id ([int]$pid) -ErrorAction Stop
        Stop-Process -Id $proc.Id -Force -ErrorAction Stop
        Write-Host "Stopped PID $pid"
    }
    catch {
        Write-Host "PID $pid already stopped"
    }
}

Remove-Item $pidFile -Force
Write-Host "Soak mode stopped."
