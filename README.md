# LinuxVHDLauncher (v0.6-demo)

LinuxVHDLauncher is a Python/PyQt6 validation and orchestration project for disposable Windows VM experiments around live Linux ISO payload staging in VHD/VHDX.

**v0.6-demo can build and validate a demo live-ISO VHD/VHDX payload in a Windows VM. Boot registration remains experimental and must be validated by a manual VM reboot test. This is not a production Linux installer.**

## Scope in v0.6-demo

Implemented:

- Live ISO inspection (`demo inspect-iso`) with SHA-256 and layout detection.
- Live VHD/VHDX payload planning (`demo live plan`) with explicit blockers/warnings.
- Guarded live payload build flow (`demo live build-vhd`) including EFI/data partition staging plan and artifact reports.
- Experimental, safety-gated registration strategy layer (`demo live register-bcd`) that blocks unsupported paths rather than faking success.
- Combined flow (`demo live install`) and guarded uninstall (`demo live uninstall`).
- Manual post-reboot evidence command (`demo live mark-boot-result`).
- Validation report artifacts, operation plans, rollback evidence, and bundle export.

Not guaranteed / not confirmed:

- Guaranteed Linux bootability from generated entry.
- Confirmed direct `BCD -> Linux EFI inside VHDX` chain on all systems.
- Production-safe installer behavior.

## Safety Model

Real Windows mutation operations are blocked unless all required flags and checks are satisfied:

- Windows host
- administrator privileges
- `--execute-real-windows-ops`
- `--i-understand-this-is-experimental`
- `--confirm-vm-snapshot`
- `--no-dry-run`
- lab/report directory constraints and rollback/report requirements

Default mode is dry-run.

## CLI Examples

Linux-safe dry-run examples:

```bash
python -m linux_vhd_launcher.cli doctor --json
python -m linux_vhd_launcher.cli demo inspect-iso --iso ./ubuntu.iso --json
python -m linux_vhd_launcher.cli demo live plan \
  --iso ./ubuntu.iso \
  --vhd ./lab/ubuntu-live.vhdx \
  --size-gb 12 \
  --lab-dir ./lab \
  --json
python -m linux_vhd_launcher.cli demo live build-vhd \
  --iso ./ubuntu.iso \
  --vhd ./lab/ubuntu-live.vhdx \
  --size-gb 12 \
  --lab-dir ./lab \
  --report-dir ./validation_reports/live-demo \
  --json
```

Real Windows VM operations (disposable VM snapshot only):

```bash
python -m linux_vhd_launcher.cli demo live build-vhd \
  --iso C:\\ISOs\\ubuntu.iso \
  --vhd C:\\LVHLab\\ubuntu-live.vhdx \
  --size-gb 12 \
  --lab-dir C:\\LVHLab \
  --report-dir C:\\LVHLab\\reports \
  --execute-real-windows-ops \
  --i-understand-this-is-experimental \
  --confirm-vm-snapshot \
  --no-dry-run \
  --json
```

## Documentation

- [Live VHD feasibility](docs/LIVE_VHD_BOOT_FEASIBILITY.md)
- [Live VHD demo workflow](docs/LIVE_VHD_DEMO.md)
- [Live ISO payload details](docs/LIVE_ISO_PAYLOAD.md)
- [Ubuntu GRUB loopback notes](docs/GRUB_LOOPBACK_UBUNTU.md)
- [BCD registration strategy](docs/BCD_LIVE_REGISTRATION.md)
- [Windows VM test protocol](docs/WINDOWS_VM_TEST_PROTOCOL.md)
- [Safety model](docs/SAFETY.md)

## Development

```bash
python -m compileall linux_vhd_launcher
python -m pytest
.venv/smoke/bin/ruff check .
.venv/smoke/bin/mypy linux_vhd_launcher
.venv/smoke/bin/pyright
```
