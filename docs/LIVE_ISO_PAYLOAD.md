# LIVE_ISO_PAYLOAD

This document describes payload staging only (not full Linux installation).

## LiveIsoInfo model

Collected fields:

- `iso_path`, `sha256`, `size_bytes`
- `distro`, `version` (best-effort detection)
- `has_efi_boot`, `has_shim`, `has_grub`
- `has_casper_kernel`, `kernel_path`, `initrd_path`

## Inspection behavior

- File input: hashes ISO and mounts read-only on Windows via `Mount-DiskImage`.
- Directory input (test mode): inspects an extracted/fake ISO tree.
- Detects expected Ubuntu live layout (`EFI/BOOT`, `casper/*`).
- Does not unpack entire ISO contents blindly.

## LiveVhdLayout

- VHD format: `vhdx` preferred.
- GPT initialization.
- EFI partition (FAT32) + data partition (`ntfs` preferred).
- ISO copied into data partition path like `/live/<iso_name>`.
- `grub.cfg` generated under `EFI/BOOT/grub.cfg`.

## Build output artifacts

- `LiveIsoInfo.json`
- `LiveVhdLayout.json`
- `LiveVhdBuildPlan.json`
- `OperationPlan.json`
- `live_build_outcome.json` (executed command evidence)
- `live_vhd_artifact_hashes.json`

## Safety boundaries

Real build is refused unless:

- Windows host
- admin rights
- `--execute-real-windows-ops`
- `--i-understand-this-is-experimental`
- `--confirm-vm-snapshot`
- `--no-dry-run`
- target VHD is inside allowed lab dir

If failure occurs before registration, rollback tries detach + partial VHD cleanup.
