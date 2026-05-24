# BCD_LIVE_REGISTRATION

Boot registration is separated from payload build.

## Strategies

- `blocked`: explicit blocker, no mutation.
- `auto`: currently resolves to blocked safe mode.
- `firmware`: placeholder strategy, returns blocker.
- `bootmgr`: experimental BCDEdit mutation path.
- `bootmgr-experimental-vhd`: explicit unsafe-gated BCD VHD experiment for disposable VM snapshot.

## Safety gate (required for real mutation)

- Windows
- admin
- `--execute-real-windows-ops`
- `--i-understand-this-is-experimental`
- `--confirm-vm-snapshot`
- `--no-dry-run`
- lab/report constraints
- BCD backup artifact path

## Explicit prohibitions in demo

- No `{bootmgr}` path rewrite.
- No default entry mutation.
- No `displayorder` mutation except `/addlast` for the experimental GUID.
- No automatic `bcdedit /import` restore (emergency only, manual mode).
- No Secure Boot setting changes.

## Experimental command family

- `bcdedit /enum all`
- `bcdedit /enum firmware`
- `bcdedit /export <backup>`
- `bcdedit /copy {current} /d "LinuxVHDLauncher Ubuntu Live VHDX EXPERIMENT"`
- `bcdedit /set <guid> device ...`
- `bcdedit /set <guid> osdevice ...`
- `bcdedit /set <guid> path ...`
- `bcdedit /displayorder <guid> /addlast`
- rollback: `bcdedit /delete <guid> /f`

## Artifacts

- `bcd_backup_live_registration.bcd`
- `bcd_baseline_before.txt`
- `bcd_baseline_after.txt`
- `bcd_baseline_diff.txt`
- `live_registration_manifest.json`
- `live_registration_outcome.json`
- `live_unregistration_outcome.json`

## Support boundary

- Microsoft documents Native Boot VHD/VHDX for Windows boot entries.
- Linux live boot through this chain is unsupported/experimental in this project.
- Successful command execution does not imply Linux boot success.
- Manual reboot verification in VM is mandatory.
- VM snapshot is mandatory before real mutation.

## Emergency rollback

1. Delete experimental entry:
   - `bcdedit /delete {GUID} /f`
2. If store corruption is suspected, use backup explicitly:
   - `bcdedit /import <path-to-bcd-backup>`
3. Revert VM snapshot.

## Confirmation level

Direct chain `BCD -> Linux EFI inside VHDX` is **не подтверждено**. Registration success does not imply boot success.
