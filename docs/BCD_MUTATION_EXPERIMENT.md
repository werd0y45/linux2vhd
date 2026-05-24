# BCD Mutation Experiment (v0.5)

`validation windows-bcd-mutation-smoke` is a narrowly-scoped experiment stage.

## What it tests

1. Export BCD backup.
2. Create temporary test BCD entry.
3. Capture temporary GUID.
4. Delete temporary entry.
5. Verify entry is gone.
6. Record rollback evidence.

Entry name used by this stage:

`LinuxVHDLauncher TEMP VALIDATION ENTRY - SAFE TO DELETE`

## What it does not test

- Linux boot success.
- Production boot chain correctness.
- Secure Boot policy compatibility for Linux payloads.

## Required flags

- `--execute-real-windows-ops`
- `--i-understand-this-is-experimental`
- `--no-dry-run`
- `--report-dir <path>`
- `--lab-dir <path>`
- `--confirm-vm-snapshot`

## Displayorder behavior

- By default, display order is **not changed**.
- Optional experiment only with:
  - `--include-displayorder-experiment`

This keeps default stage minimally invasive.

## Rollback behavior

- Rollback is always attempted when temporary entry was created.
- Rollback evidence is written into report.
- If delete/verify fails, campaign status must be treated as failed/blocked.

## Emergency cleanup

If automatic cleanup is incomplete:

1. Run `bcdedit /enum all`.
2. Delete temporary entry GUID manually.
3. Restore from BCD backup artifact.
4. Revert VM snapshot if any doubt remains.

## Scope warning

This stage is experimental and VM-only. It is not a production installer path.
