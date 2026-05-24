# LIVE_VHD_DEMO

`v0.6-demo` targets disposable Windows 10/11 UEFI VMs with snapshot/checkpoint.

## Preconditions

- Admin PowerShell session.
- Snapshot/checkpoint confirmed.
- All mutable artifacts constrained to a lab directory, e.g. `C:\LVHLab`.
- Default mode is dry-run.

## Command Flow

1. Inspect ISO:

```powershell
python -m linux_vhd_launcher.cli demo inspect-iso --iso C:\ISOs\ubuntu.iso --json
```

2. Plan payload:

```powershell
python -m linux_vhd_launcher.cli demo live plan --iso C:\ISOs\ubuntu.iso --vhd C:\LVHLab\ubuntu-live.vhdx --size-gb 12 --lab-dir C:\LVHLab --json
```

3. Build payload (dry-run default):

```powershell
python -m linux_vhd_launcher.cli demo live build-vhd --iso C:\ISOs\ubuntu.iso --vhd C:\LVHLab\ubuntu-live.vhdx --size-gb 12 --lab-dir C:\LVHLab --report-dir C:\LVHLab\reports --json
```

4. Real payload build (unsafe gate required):

```powershell
python -m linux_vhd_launcher.cli demo live build-vhd --iso C:\ISOs\ubuntu.iso --vhd C:\LVHLab\ubuntu-live.vhdx --size-gb 12 --lab-dir C:\LVHLab --report-dir C:\LVHLab\reports --execute-real-windows-ops --i-understand-this-is-experimental --confirm-vm-snapshot --no-dry-run --json
```

5. Registration experiment:

```powershell
python -m linux_vhd_launcher.cli demo live register-bcd --vhd C:\LVHLab\ubuntu-live.vhdx --lab-dir C:\LVHLab --report-dir C:\LVHLab\reports --strategy auto --json
```

6. Combined:

```powershell
python -m linux_vhd_launcher.cli demo live install --iso C:\ISOs\ubuntu.iso --vhd C:\LVHLab\ubuntu-live.vhdx --size-gb 12 --lab-dir C:\LVHLab --report-dir C:\LVHLab\reports --strategy auto --json
```

7. Post-reboot manual evidence:

```powershell
python -m linux_vhd_launcher.cli demo live mark-boot-result --report-dir C:\LVHLab\reports --result booted --notes "Reached Ubuntu live menu" --json
```

## Status Semantics

- `planned`: dry-run or planned-only result.
- `payload_built`: payload artifact build completed.
- `registration_blocked`: strategy intentionally blocked unsupported path.
- `registration_experimental_done`: experimental registration mutation executed.
- `bootability_unverified`: no manual reboot evidence yet.
- `bootability_confirmed_manual`: manual reboot evidence marked as booted.

Bootability is never claimed unless manually confirmed by VM reboot test.
