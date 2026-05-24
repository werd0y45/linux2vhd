# Safety Model

## Dangerous operations

Potentially dangerous actions:
- Creating/attaching/detaching VHD/VHDX on Windows.
- Modifying Boot Configuration Data (BCD).

These actions are now hard-gated by `RealWindowsOpsGate` and require explicit CLI opt-in flags.
For v0.4 guarded real operations are allowed only when all conditions are true:
- Windows platform.
- Administrator token.
- Explicit execute flag.
- Dry-run disabled for the command.
- Experimental confirmation token provided.
- Rollback plan is defined.
- Validation report path is configured.
- Target path is inside allowed validation lab directory.

No code path is intended to repartition physical disks.

## dry-run behavior

`CommandRunner(dry_run=True)` returns successful `CommandResult` without executing system commands.
Dry-run is the default safe mode for Linux validation.

## BCD backup strategy

Before BCD mutation, installer exports backup via:
- `bcdedit /export <backup-path>`

Backup path is logged and persisted in registry metadata when available.
Real mode requires backup path to be configured before operation execution.

## Uninstall behavior

Uninstall removes:
- BCD entry.
- Local registry record.
- Best-effort VHD detach.

## Secure Boot limitations

Current prototype only validates required EFI files exist in staging.
It does not:
- disable Secure Boot,
- sign bootloaders,
- guarantee trust chain compatibility.

See `docs/FEASIBILITY.md` for boot-chain caveats.
