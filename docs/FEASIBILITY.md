# Feasibility: Linux Boot via Windows Boot Stack (v0.3)

## Scope

This document distinguishes:
- Microsoft-documented support boundaries.
- Experimental Linux boot-chain options.
- VM validation work still required.

## Documented by Microsoft

Documented and supported (Windows-focused):
- BCDEdit store editing and boot entry manipulation (`/copy`, `/set`, `/displayorder`, `/delete`, `/export`).
- BCDBoot for installing/repairing Windows boot files and BCD setup.
- Native Boot to VHD/VHDX for Windows images.
- Win32 Virtual Disk API (`CreateVirtualDisk`, `OpenVirtualDisk`, `AttachVirtualDisk`, `DetachVirtualDisk`).

Important boundary:
- Native Boot from VHD/VHDX documentation is explicitly oriented to Windows images and Windows boot files.

## Not Documented as Supported

Not explicitly documented by Microsoft as supported:
- Guaranteed Linux boot from VHDX through Windows Boot Manager using BCDEdit-created entries.
- A generic claim that a copied `{current}` entry can be converted to reliable Linux boot chain across machines.

## Option Matrix

| Option | Documentation Status | Pros | Risks | VM Checks Required |
|---|---|---|---|---|
| Native Boot to VHDX (Windows image) | Microsoft-documented | Stable reference workflow | Windows-only payload scope | Confirm baseline behavior in same VM |
| `bcdedit /copy {current}` then set Linux-ish device/path | Experimental/unsupported for Linux | Uses documented BCDEdit primitives | Entry type/path semantics may not match Linux chain | Entry creation, menu visibility, rollback, reboot behavior |
| Windows Boot Manager -> EFI binary path | Experimental for Linux chain | Clear separation of payload handoff | Secure Boot signature trust may block binary | Secure Boot on/off matrix, binary trust behavior |
| Windows Boot Manager -> shim -> grub | Experimental | Potential distro-aligned Secure Boot path | Shim/grub trust state and config variability | Distro-specific shim/grub validation in VM |
| ESP + UEFI boot entry path (outside current BCD-only approach) | Partially documented at platform level, not integrated here | Could align with firmware-native flow | ESP manipulation complexity and rollback risk | ESP layout, entry persistence, firmware boot ordering |

## BCDBoot and ESP Considerations

Possible future direction to validate:
- Hybrid approach that prepares EFI artifacts on ESP and uses documented boot-file tooling patterns.
- Evaluate whether BCDBoot/ESP workflow is safer than current experimental BCD planning for Linux handoff.

No production claim is made for this path in v0.3.

## Virtual Disk Backend Status

- `diskpart` backend remains operational for prototype execution.
- `VirtualDiskApiBackend` skeleton now exists with ctypes signatures and safety gating.
- Real virtdisk ctypes execution remains feature-flagged and VM-only.

## Required VM Validation Areas

1. BCD model for Linux chain behavior.
2. Windows Boot Manager handoff to EFI binary/shim/grub.
3. Secure Boot / BitLocker / UEFI firmware edge cases.
4. Whether ESP-oriented path is required for practical reliability.

## References

- BCDEdit command-line options: https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/bcdedit-command-line-options?view=windows-11
- Add boot entries: https://learn.microsoft.com/en-au/windows-hardware/drivers/devtest/adding-boot-entries
- Native Boot to VHDX: https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/boot-to-vhd--native-boot--add-a-virtual-hard-disk-to-the-boot-menu?view=windows-11
- BCDBoot options: https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/bcdboot-command-line-options-techref-di?view=windows-11
- Virtual Disk API overview: https://learn.microsoft.com/en-us/windows/win32/vstor/about-vhd
