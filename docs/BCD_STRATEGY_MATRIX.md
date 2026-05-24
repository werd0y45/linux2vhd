# BCD Strategy Matrix (v0.5)

This matrix captures strategy options for LinuxVHDLauncher validation work.

Important boundary:

- Microsoft documents **Native Boot from VHD/VHDX for Windows workloads**.
- That does **not** guarantee a production-ready Linux installer path through Windows Boot Manager.

| Strategy | Summary | Documented by Microsoft? | Expected Linux compatibility | Secure Boot implications | Rollback method | VM test needed | Production recommendation |
|---|---|---|---|---|---|---|---|
| Strategy A | Microsoft-supported Windows Native Boot from VHDX | yes (Windows workloads) | low/uncertain for Linux payload chaining | depends on shim/grub signatures and policy state | remove entry, detach/delete VHDX, restore snapshot | yes | no (Linux path not guaranteed) |
| Strategy B | Windows Boot Manager -> copied current loader entry (experimental) | partial | uncertain; loader element edits can be fragile | may require temporary policy changes | `bcdedit /delete {guid} /f`, restore backup | yes | no |
| Strategy C | Windows Boot Manager -> direct EFI application/shim chain (experimental) | partial | uncertain; firmware/BCD path behaviors vary | strong dependency on trusted signatures and DB state | restore BCD backup, remove artifacts, snapshot revert | yes | no |
| Strategy D | UEFI NVRAM boot entry -> shim/grub on ESP | partial (UEFI tooling exists) | medium but platform-dependent | direct UEFI Secure Boot enforcement applies | remove NVRAM entry and restore ESP files | yes | no |
| Strategy E | External fallback via LiveUSB/Ventoy for recovery/testing only | no | high for recovery workflows | independent from Windows Boot Manager | external media boot only | yes | yes, as fallback only |

## Notes

- v0.5 objective is controlled VM validation and evidence collection.
- Any BCD/UEFI mutation remains behind explicit unsafe gate.
- `windows-bcd-mutation-smoke` is intentionally limited and keeps `displayorder` unchanged by default.
