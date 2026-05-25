# FIRMWARE_EFI_STAGED

## Why copied `{current}` failed

Observed Windows VM evidence:

- Entry created from `bcdedit /copy {current}` with VHD device/osdevice and `path \EFI\BOOT\BOOTX64.EFI`.
- Selecting entry entered Windows Automatic Repair.
- GRUB/Ubuntu was not reached.

Interpretation:

- Copied `{current}` remains a Windows OS loader object.
- `systemroot`, recovery, and osloader semantics remain Windows-oriented.
- Setting `path` to Linux EFI file does not convert entry into a generic EFI chainloader.

## How firmware-efi-staged differs

- Does **not** copy `{current}`.
- Builds an ESP staging plan for EFI files under lab-controlled path:
  - `\EFI\LinuxVHDLauncher\ubuntu-live\BOOTX64.EFI`
  - `\EFI\LinuxVHDLauncher\ubuntu-live\grubx64.efi`
  - `\EFI\LinuxVHDLauncher\ubuntu-live\grub.cfg`
- Produces rollback plan for staged files and optional entry delete.

## Loader location options

- Firmware-visible ESP path on Windows: potentially usable for UEFI boot menu experiments.
- EFI binary inside VHDX via BCD/firmware: **не подтверждено**.
- Current implementation keeps real mode blocked until documented entry creation path is validated.

## Documented command building blocks used in planning

- `bcdedit /enum firmware`
- `bcdedit /create ... /application ...` (planning only)
- `bcdedit /set`
- `bcdedit /displayorder`
- `bcdedit /delete`
- `mountvol /s` and `mountvol /d`
- offline capability probe: `bcdedit /createstore`, `bcdedit /store <probe> /create`, `bcdedit /store <probe> /enum all /v`

## Probe dependency

- Run `demo bcd probe-application-types` first.
- If offline report contains `bootapp` in `supported_types`, project enables dry-run strategy `firmware-efi-bootapp-probe`.
- If `bootapp` is absent or rejected, `firmware-efi-staged` stays blocked for real mode and docs status remains: `BCD generic EFI chain remains unconfirmed`.

## What remains unverified until reboot test

- Whether firmware entry creation path is valid for this Linux EFI scenario.
- Whether staged loader reaches GRUB and Ubuntu live chain.
- Secure Boot behavior with shim/grub and signatures in this staged path.

## Current safety posture

- `firmware-efi-staged` default: dry-run planning.
- Real mode requires explicit unsafe flags:
  - `--allow-esp-write`
  - `--allow-firmware-entry`
  - `--allow-secure-boot-experiment`
- Even with flags, real mode remains blocked pending documented+validated firmware entry flow.
