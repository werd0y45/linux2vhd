# VM Runner (v0.5)

LinuxVHDLauncher v0.5 introduces a hypervisor-agnostic VM runner harness for validation campaigns.

## Why snapshot is required

BCD/VHD experiments can affect bootability. Snapshot requirement enforces rollback-first execution:

- run only in disposable VM,
- validate temporary mutations,
- restore baseline after failure or uncertainty.

## Runner types

## `manual`

- No automation of VM operations.
- Operator must pass `--confirm-vm-snapshot` for mutation stages.
- Recommended default for first real Windows VM campaign.

## `external`

- Supports command hooks (`before`/`after`/`collect`) from CLI wiring.
- Dry-run behavior is default unless mutation is explicitly allowed.
- Useful when VM orchestration is done by external scripts/tooling.

## `hyperv` (skeleton in v0.5)

- Planning/probe only.
- No automatic checkpoint creation/restore in v0.5.
- Real Hyper-V mutation actions stay explicitly gated and documented.

## CLI

- `validation vm-status`
  - returns `VmRunnerStatus` with warnings and snapshot capability indicators.
- `validation run-campaign`
  - orchestrates campaign flow through runner lifecycle:
    - `check_status`
    - `before_campaign`
    - validation stages
    - `after_campaign`
    - `collect_artifacts`

## Safety notes

- VM runner is an orchestration layer, not a bypass for safety gate.
- Real Windows operations still require:
  - `--execute-real-windows-ops`
  - `--i-understand-this-is-experimental`
  - `--no-dry-run`
  - report + lab constraints.
