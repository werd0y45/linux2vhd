# WINDOWS_VM_TEST_PROTOCOL

Date: 2026-05-24
Target: disposable Windows 10/11 UEFI VM only

## Hard requirements

- Create VM snapshot/checkpoint before any real operation.
- Run as Administrator.
- Use isolated lab dir (example `C:\LVHLab`).
- Do not run on production host.

## Dry-run protocol

1. `python -m linux_vhd_launcher.cli doctor --json`
2. `python -m linux_vhd_launcher.cli validation init --report-dir C:\LVHLab\reports`
3. `python -m linux_vhd_launcher.cli demo inspect-iso --iso C:\ISOs\ubuntu.iso --json`
4. `python -m linux_vhd_launcher.cli demo live plan --iso C:\ISOs\ubuntu.iso --vhd C:\LVHLab\ubuntu-live.vhdx --size-gb 12 --lab-dir C:\LVHLab --json`
5. `python -m linux_vhd_launcher.cli demo live build-vhd --iso C:\ISOs\ubuntu.iso --vhd C:\LVHLab\ubuntu-live.vhdx --size-gb 12 --lab-dir C:\LVHLab --report-dir C:\LVHLab\reports --json`

Expected: no real disk/BCD mutation.

## Real demo protocol (unsafe gate)

1. Confirm fresh snapshot/checkpoint.
2. Execute real build:
   - add `--execute-real-windows-ops --i-understand-this-is-experimental --confirm-vm-snapshot --no-dry-run`
3. Optional registration experiment:
   - `demo live register-bcd ... --strategy bootmgr --execute-real-windows-ops --i-understand-this-is-experimental --confirm-vm-snapshot --no-dry-run`
4. Reboot VM manually and capture observed behavior.
5. Record outcome:
   - `demo live mark-boot-result --report-dir C:\LVHLab\reports --result booted|failed|not-tested --notes "..."`

## Evidence collection

- Keep `report_dir` artifacts (plans, outcomes, BCD backup, baseline diff, command evidence).
- Create validation bundle:
  - `python -m linux_vhd_launcher.cli validation bundle --report-dir C:\LVHLab\reports --format zip`

## Emergency rollback

- Delete temporary demo GUID if created.
- Use `bcdedit /import <backup.bcd>` only in explicit manual emergency mode.
- Revert VM snapshot when in doubt.

## Interpretation

- `payload_built` means artifact created.
- `registration_experimental_done` means mutation attempted.
- Bootability is confirmed only after reboot evidence shows `booted`.
