# BCD_LIVE_REGISTRATION

Boot registration is separated from payload build.

## Strategies

- `blocked`: explicit blocker, no mutation.
- `auto`: currently resolves to blocked safe mode.
- `firmware`: placeholder strategy, returns blocker.
- `bootmgr`: experimental BCDEdit mutation path.
- `bootmgr-experimental-vhd`: explicit unsafe-gated BCD VHD experiment for disposable VM snapshot.
- `firmware-efi-staged`: ESP staging-oriented strategy; currently plan-first and real mode blocked pending documented firmware-entry validation.
- `firmware-efi-bootapp-system-dry-run`: dry-run strategy that activates only after offline probe confirms BOOTAPP `create` + `device` + `path` acceptance.
- `bootapp-vhd-system-dry-run`: dry-run strategy that activates only after offline probe confirms BOOTAPP `device vhd=[...]` + `path \EFI\BOOT\BOOTX64.EFI` acceptance.
- `bootapp-vhd-system-experimental`: real unsafe-gated strategy that creates a brand new BOOTAPP entry and points it to VHDX device without using copied Windows loader.

## Known Failure Evidence (Windows 10 VM)

Observed reboot evidence:

- `bootmgr-experimental-vhd` entry was created from copied `{current}`.
- Entry fields were changed to VHD device/osdevice and `\EFI\BOOT\BOOTX64.EFI`.
- Selecting the entry led to Windows Automatic Repair; GRUB/Ubuntu was not reached.
- Windows remained recoverable and booted normally afterward.

Failure analysis:

- Copying `{current}` preserves Windows OS loader semantics.
- `systemroot`/recovery/osloader behavior remains tied to Windows loader expectations.
- Setting `path \EFI\BOOT\BOOTX64.EFI` on copied Windows loader entry does not convert it into a generic EFI chainloader.

As a result, strategy is marked known-failed with id:

- `copied-current-osloader-vhd`

New contrast:

- `bootapp-vhd-system-experimental` does not use `/copy {current}` and does not set `osdevice/systemroot/recoverysequence/resumeobject`.
- It is still experimental: offline parser acceptance does not prove reboot bootability.

## Safety gate (required for real mutation)

- Windows
- admin
- `--execute-real-windows-ops`
- `--i-understand-this-is-experimental`
- `--confirm-vm-snapshot`
- `--allow-known-failed-strategy` (required only for strategies marked known-failed)
- successful `bcd_bootapp_vhd_device_probe.json` with `conclusion=bootapp_vhd_device_supported` (unless `--allow-unprobed-bootapp-vhd` is explicitly set)
- `--no-dry-run`
- lab/report constraints
- BCD backup artifact path

## Explicit prohibitions in demo

- No `{bootmgr}` path rewrite.
- No default entry mutation.
- No `displayorder` mutation except `/addlast` for the experimental GUID.
- No automatic `bcdedit /import` restore (emergency only, manual mode).
- No Secure Boot setting changes.
- For BOOTAPP VHD strategy, no use of:
  - `osdevice`
  - `systemroot`
  - `recoverysequence`
  - `resumeobject`

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

## Firmware-efi-staged planning scope

- Inspects payload metadata and prepares `EspStagingPlan`.
- Plans ESP mount via `mountvol S: /s`.
- Plans staging under `\\EFI\\LinuxVHDLauncher\\ubuntu-live\\`.
- Plans rollback:
  - delete entry (`bcdedit /delete {GUID} /f`) if created,
  - remove staged ESP directory,
  - unmount ESP (`mountvol S: /d`).
- Does not mutate `{bootmgr}` path or default entry.
- Does not claim bootability.
- Caveat:
  - ESP-staged loader may not see ISO that is stored inside VHDX payload.
  - This is why BOOTAPP VHD-device probe is tracked as the next closer experiment.

## Offline BOOTAPP probes

- Command:
  - `demo bcd probe-application-types --lab-dir <lab> --report-dir <reports> --json`
- Command:
  - `demo bcd probe-bootapp-elements --lab-dir <lab> --report-dir <reports> --json`
- Analyzer:
  - `demo bcd analyze-bootapp-probe --probe-report <reports>\\bcd_bootapp_elements_probe.json --json`
- Command:
  - `demo bcd probe-bootapp-vhd-device --vhd <vhd-path> --lab-dir <lab> --report-dir <reports> --json`
- Analyzer:
  - `demo bcd analyze-bootapp-vhd-device-probe --probe-report <reports>\\bcd_bootapp_vhd_device_probe.json --json`
- Uses offline store only:
  - `bcdedit /createstore <lab>\\bcd_probe\\bcd_probe.bcd`
  - `bcdedit /store <probe-store> /create ... /application osloader|bootsector|bootapp`
  - `bcdedit /store <probe-store> /enum all /v`
- Uses separate offline store for BOOTAPP element set probes:
  - `bcdedit /store <probe-store> /create ... /application bootapp`
  - `bcdedit /store <probe-store> /set {GUID} device partition=C:`
  - `bcdedit /store <probe-store> /set {GUID} path \EFI\LinuxVHDLauncher\ubuntu-live\BOOTX64.EFI`
  - `bcdedit /store <probe-store> /enum all /v`
- Probe result informs whether `firmware-efi-bootapp-system-dry-run` can generate an extended dry-run plan.
- Even if `device/path` are accepted offline, runtime Linux EFI boot remains **не подтверждено**.
- Uses separate offline store for BOOTAPP VHD-device probes:
  - `bcdedit /store <probe-store> /create ... /application bootapp`
  - `bcdedit /store <probe-store> /set {GUID} device vhd=[C:]\\LVHLab\\ubuntu-live.vhdx`
  - `bcdedit /store <probe-store> /set {GUID} path \EFI\BOOT\BOOTX64.EFI`
  - `bcdedit /store <probe-store> /enum all /v`
- Probe result informs whether `bootapp-vhd-system-dry-run` can generate dry-run system-mutation plan.
- Probe result is also a hard gate for `bootapp-vhd-system-experimental` by default.
- Offline acceptance still does not prove bootability.

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
- Documented generic firmware EFI entry creation flow for this Linux path is not confirmed here.
- Successful command execution does not imply Linux boot success.
- Manual reboot verification in VM is mandatory.
- VM snapshot is mandatory before real mutation.
- Known-failed strategies return `registration_experimental_done_but_boot_failed` status when executed.

## Emergency rollback

1. Delete experimental entry:
   - `bcdedit /delete {GUID} /f`
2. If store corruption is suspected, use backup explicitly:
   - `bcdedit /import <path-to-bcd-backup>`
3. Revert VM snapshot.

## Confirmation level

Direct chain `BCD -> Linux EFI inside VHDX` is **не подтверждено**. Registration success does not imply boot success.

## Manual reboot evidence

After running real experimental registration, record outcome explicitly:

- `demo live mark-boot-result --report-dir <reports> --result booted --notes "..."`
- `demo live mark-boot-result --report-dir <reports> --result failed --notes "..."`
- `demo live mark-boot-result --report-dir <reports> --result not-tested --notes "..."`
