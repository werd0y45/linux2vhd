# VirtDisk Backend Skeleton (v0.3)

## Scope

`VirtualDiskApiBackend` is introduced as a structural skeleton for future WinAPI-based virtual disk management.

Current state:
- Interface and method layout are present.
- ctypes constants/signatures are separated in `linux_vhd_launcher/system/windows_virtdisk_ctypes.py`.
- Real calls are feature-flagged and not enabled by default.
- Safety gate is mandatory.

## WinAPI Functions Required

From `virtdisk.h` / Virtual Disk API:
- `CreateVirtualDisk`
- `OpenVirtualDisk`
- `AttachVirtualDisk`
- `DetachVirtualDisk`
- `CloseHandle` (kernel32)

## Structures/Types Needed

- `VIRTUAL_STORAGE_TYPE`
- `CREATE_VIRTUAL_DISK_PARAMETERS` (currently v2 skeleton)
- `OPEN_VIRTUAL_DISK_PARAMETERS` (currently v1 skeleton)
- virtual disk access flags and operation flags

## Safety Model

Before any real operation, all conditions must pass:
- OS is Windows
- process has admin rights
- explicit flag enabled (`--execute-real-windows-ops`)
- `dry_run == False`
- backup path configured
- confirmation token provided (`--i-understand-this-is-experimental`)

Otherwise backend raises `UnsafeRealOperationError`.

## Why VirtDisk over diskpart

Potential advantages:
- Native API contracts with explicit structures and flags.
- Better control over handle lifecycle and error codes.
- More deterministic integration points for typed wrappers and tests.

`diskpart` remains useful for early prototyping but is shell-script oriented and harder to reason about programmatically.

## Feature Flag

Real ctypes calls are disabled by default.
Enable only on disposable Windows VM:

```powershell
$env:LINUX_VHD_LAUNCHER_ENABLE_VIRTDISK_CTYPES = "1"
```

## Windows VM Test Strategy

1. Create VM snapshot.
2. Verify elevated shell.
3. Run guarded commands with explicit flags.
4. Validate create/open/attach/detach flow on non-production VHDX.
5. Capture error codes and logs.
6. Revert snapshot after each experiment.

## Known Gaps (v0.3)

- No production-grade parameter completeness for all creation/open variants.
- No robust retry policy for transient attach/detach failures.
- No end-to-end integration guarantee with Linux payload boot chain.
