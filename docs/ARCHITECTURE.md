# Architecture

## Module layout

- `linux_vhd_launcher.cli`: CLI entrypoint and dependency wiring.
- `linux_vhd_launcher.app`: GUI entrypoint.
- `linux_vhd_launcher.config`: config + versioned/atomic registry persistence.
- `linux_vhd_launcher.models`: domain dataclasses.
- `linux_vhd_launcher.errors`: domain exceptions and warnings.
- `linux_vhd_launcher.services.*`: business orchestration.
- `linux_vhd_launcher.services.operation_planners`: structured planning layer.
- `linux_vhd_launcher.system.*`: OS/backend abstractions.
- `linux_vhd_launcher.gui.*`: PyQt6 wizard UI.

## Boot layer split

Boot operations are separated into:

1. Command builder: `BcdCommandBuilder`
- Responsible for generating BCDEdit command tuples.
- Unit-tested independently.

2. Backend executor: `RunnerBcdExecutor` + `CommandBasedBcdBackend`
- Executes commands through `CommandRunner`.
- Enforces Windows admin checks for real mode.

3. Registry updater: `RegistryUpdater`
- Saves/removes local install records.
- Uses atomic writes via `RegistryStore`.

## Safety gate

Real Windows operations are guarded by `RealWindowsOpsGate`.

Required conditions:
- Windows platform.
- Admin rights.
- Explicit execution flag.
- Non-dry-run mode.
- Configured backup path.
- Explicit experimental confirmation token.

Without these conditions, backends raise `UnsafeRealOperationError`.

## Install flow

`InstallerService.install()` executes:
1. Validate ISO.
2. Build ISO metadata and distro mapping.
3. Check free space.
4. Create VHD/VHDX.
5. Attach VHD/VHDX.
6. Run deployment backend (placeholder).
7. Verify secure-boot file chain.
8. Backup BCD.
9. Create/configure BCD entry.
10. Save registry item.
11. Detach VHD/VHDX.

## Rollback stack

Installer uses a rollback action stack:
- A rollback action is registered only after the corresponding forward action succeeds.
- On failure, rollback actions run in reverse order.
- Rollback errors are aggregated.
- Original install exception is preserved as `__cause__` when rollback also fails.

## Why GUI is separated

GUI never invokes `subprocess` or platform commands directly.
All potentially dangerous operations are routed through service/backend abstractions.
