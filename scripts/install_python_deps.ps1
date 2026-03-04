param(
    [string]$ProjectRoot = "",
    [string]$VenvDir = ".venv",
    [switch]$CreateVenv,
    [switch]$UpgradePip
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

Set-Location $ProjectRoot

$requirementsPath = Join-Path $ProjectRoot "requirements.txt"
if (!(Test-Path $requirementsPath)) {
    throw "requirements.txt not found: $requirementsPath"
}

$venvPath = Join-Path $ProjectRoot $VenvDir
if ($CreateVenv) {
    if (!(Test-Path $venvPath)) {
        Write-Host "Creating virtual environment: $venvPath"
        python -m venv $venvPath
    }
}

$pipExe = Join-Path $venvPath "Scripts\\pip.exe"
if (Test-Path $pipExe) {
    $pipCmd = $pipExe
} else {
    $pipCmd = "pip"
}

if ($UpgradePip) {
    Write-Host "Upgrading pip..."
    & $pipCmd install --upgrade pip
}

Write-Host "Installing dependencies from requirements.txt ..."
& $pipCmd install -r $requirementsPath

Write-Host "Done."
if (Test-Path $pipExe) {
    Write-Host "Tip: activate venv with:"
    Write-Host "  $venvPath\\Scripts\\Activate.ps1"
}
