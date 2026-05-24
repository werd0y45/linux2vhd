# SAFETY

This project is demo-first for disposable VM validation, not production installation.

## Non-negotiable rules

- Never mutate Windows boot on a production machine.
- Always snapshot VM before real operations.
- Keep all mutable files in lab directory.
- Do not touch physical partitions except read-only probing and controlled BCD export/entry mutation.

## Real operation gates

Real operations require all of:

- Windows host
- admin privileges
- `--execute-real-windows-ops`
- `--i-understand-this-is-experimental`
- `--confirm-vm-snapshot`
- `--no-dry-run`

Additionally:

- rollback plan must exist
- report path must exist
- target path must be inside allowed lab dir

## Prohibited shortcuts

- No silent BCD mutation.
- No unsupported `bcdedit` usage claims.
- No automatic `{bootmgr}` path changes.
- No implicit `displayorder` modifications.
- No automatic BCD import restore in normal flow.

## Explicitly unconfirmed areas

- Direct boot chain from BCD into Linux EFI payload inside VHDX is **не подтверждено**.
- EFI visibility/behavior for nested VHDX payload with arbitrary firmware paths is **не подтверждено**.

## Status vocabulary

- `payload_built` != booted system.
- `registration_experimental_done` != booted system.
- `bootability_confirmed_manual` requires real reboot evidence.
