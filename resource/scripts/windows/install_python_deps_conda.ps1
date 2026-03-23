param(
    [string]$EnvName = "Back_end_project",
    [string]$ProjectRoot = "",
    [switch]$UpgradePip
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..\\..")).Path
} else {
    $ProjectRoot = (Resolve-Path $ProjectRoot).Path
}

$requirementsPath = Join-Path $ProjectRoot "requirements.txt"
if (!(Test-Path $requirementsPath)) {
    throw "requirements.txt not found: $requirementsPath"
}

if ($UpgradePip) {
    conda run -n $EnvName python -m pip install --upgrade pip
}

conda run -n $EnvName python -m pip install -r $requirementsPath
Write-Host "Done. Installed requirements into conda env: $EnvName"
