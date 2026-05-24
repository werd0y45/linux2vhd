# BCD_LIVE_REGISTRATION

Boot registration is separated from payload build.

## Strategies

- `blocked`: explicit blocker, no mutation.
- `auto`: currently resolves to blocked safe mode.
- `firmware`: placeholder strategy, returns blocker.
- `bootmgr`: experimental BCDEdit mutation path.

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

- No automatic `displayorder` insertion.
- No `{bootmgr}` path rewrite.
- No automatic `bcdedit /import` restore (emergency only, manual mode).
- No Secure Boot setting changes.

## Experimental command family

- `bcdedit /enum all`
- `bcdedit /export <backup>`
- `bcdedit /copy {current} /d "LinuxVHDLauncher Live (Experimental)"`
- `bcdedit /set <guid> device ...`
- `bcdedit /set <guid> osdevice ...`
- `bcdedit /set <guid> path ...`
- rollback: `bcdedit /delete <guid> /f`

## Artifacts

- `bcd_backup_live_registration.bcd`
- `bcd_baseline_before.txt`
- `bcd_baseline_after.txt`
- `bcd_baseline_diff.txt`
- `live_registration_manifest.json`
- `live_registration_outcome.json`

## Confirmation level

Direct chain `BCD -> Linux EFI inside VHDX` is **не подтверждено**. Registration success does not imply boot success.
