param(
    [Parameter(Mandatory = $true)]
    [string]$IsoPath,

    [string]$LabDir = "C:\LVHLab",

    [switch]$ExecuteRealOps,

    [switch]$ConfirmSnapshot
)

$ErrorActionPreference = "Stop"

function Require-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script in an elevated PowerShell session."
    }
}

function Run-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )
    Write-Host "`n==> $Title"
    Write-Host ($Command -join " ")
    & $Command[0] $Command[1..($Command.Length - 1)]
}

Require-Admin

if (-not (Test-Path -LiteralPath $IsoPath)) {
    throw "ISO not found: $IsoPath"
}

$reportDir = Join-Path $LabDir "reports"
$vhdPath = Join-Path $LabDir "ubuntu-live.vhdx"

New-Item -ItemType Directory -Force -Path $LabDir | Out-Null
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

Run-Step -Title "Check Python" -Command @("python", "--version")
Run-Step -Title "Install dev deps" -Command @("python", "-m", "pip", "install", "-e", ".[dev]")
Run-Step -Title "Run pytest" -Command @("python", "-m", "pytest")
Run-Step -Title "Doctor" -Command @("python", "-m", "linux_vhd_launcher.cli", "doctor", "--json")
Run-Step -Title "Validation init" -Command @("python", "-m", "linux_vhd_launcher.cli", "validation", "init", "--report-dir", $reportDir)
Run-Step -Title "Inspect ISO" -Command @("python", "-m", "linux_vhd_launcher.cli", "demo", "inspect-iso", "--iso", $IsoPath, "--json")
Run-Step -Title "Plan live payload" -Command @("python", "-m", "linux_vhd_launcher.cli", "demo", "live", "plan", "--iso", $IsoPath, "--vhd", $vhdPath, "--size-gb", "12", "--lab-dir", $LabDir, "--json")
Run-Step -Title "Build live payload dry-run" -Command @("python", "-m", "linux_vhd_launcher.cli", "demo", "live", "build-vhd", "--iso", $IsoPath, "--vhd", $vhdPath, "--size-gb", "12", "--lab-dir", $LabDir, "--report-dir", $reportDir, "--json")

if ($ExecuteRealOps) {
    if (-not $ConfirmSnapshot) {
        throw "Real ops requested but -ConfirmSnapshot was not provided."
    }

    Run-Step -Title "Build live payload REAL" -Command @(
        "python", "-m", "linux_vhd_launcher.cli", "demo", "live", "build-vhd",
        "--iso", $IsoPath,
        "--vhd", $vhdPath,
        "--size-gb", "12",
        "--lab-dir", $LabDir,
        "--report-dir", $reportDir,
        "--execute-real-windows-ops",
        "--i-understand-this-is-experimental",
        "--confirm-vm-snapshot",
        "--no-dry-run",
        "--json"
    )

    Run-Step -Title "Register BCD experiment REAL" -Command @(
        "python", "-m", "linux_vhd_launcher.cli", "demo", "live", "register-bcd",
        "--vhd", $vhdPath,
        "--lab-dir", $LabDir,
        "--report-dir", $reportDir,
        "--strategy", "bootmgr",
        "--execute-real-windows-ops",
        "--i-understand-this-is-experimental",
        "--confirm-vm-snapshot",
        "--no-dry-run",
        "--json"
    )
}

Run-Step -Title "Validation bundle" -Command @("python", "-m", "linux_vhd_launcher.cli", "validation", "bundle", "--report-dir", $reportDir)

Write-Host "`nSmoke flow complete."
