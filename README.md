# LinuxVHDLauncher (v0.5)

LinuxVHDLauncher is a Python/PyQt6 orchestration project for planning and safely validating Linux-on-VHD/VHDX workflows with Windows Boot Manager integration experiments.

**v0.5 can run guarded Windows VM validation experiments, but it is still not a production Linux installer.**

## Status

Implemented in v0.5:

- Validation report schema v2 with v1 migration support.
- Extended step evidence (`CommandEvidence`, `RollbackEvidence`, probes, capabilities).
- Capability matrix scanners and CLI:
  - `validation capabilities`
- Unified telemetry and structured error recording in report JSON.
- VM runner harness abstractions:
  - `validation vm-status`
  - `validation run-campaign`
- Guarded BCD mutation experiment stage:
  - `validation windows-bcd-mutation-smoke`
- Artifact bundle export:
  - `validation bundle --report-dir ... [--redact] [--format zip|targz]`
- OperationPlan improvements (risk levels, prerequisites, expected result, rollback/verification actions).

Experimental:

- Guarded real Windows probes/smokes.
- Guarded BCD mutation experiment in disposable VM snapshots only.
- Linux boot chain through Windows Boot Manager.
- `virtdisk` ctypes real path.

Placeholder:

- Actual Linux deployment into VHD/VHDX payload.
- Finalized Secure Boot chain.
- Guaranteed bootable Linux entry.

## Safety model

Real Windows operations are blocked unless all safety conditions are satisfied:

- Host platform is Windows.
- Process has administrator rights.
- `--execute-real-windows-ops` is provided.
- Dry-run is explicitly disabled (`--no-dry-run` where applicable).
- `--i-understand-this-is-experimental` confirmation token is provided.
- Rollback plan is defined.
- Validation report path is configured.
- Target path is inside allowed validation lab directory.
- Mutation experiments require explicit VM snapshot confirmation.

Otherwise the command is refused with `UnsafeRealOperationError`.

## Quickstart (Linux-safe)

```bash
python -m linux_vhd_launcher.cli doctor
python -m linux_vhd_launcher.cli doctor --json
python -m linux_vhd_launcher.cli plan-install --iso ./sample.iso --vhd ./sample.vhdx --size-gb 20 --format vhdx --dry-run --json
python -m linux_vhd_launcher.cli plan-windows-lab --json
python -m linux_vhd_launcher.cli validation init --report-dir ./validation_reports/local
python -m linux_vhd_launcher.cli validation capabilities --report-dir ./validation_reports/local --json
python -m linux_vhd_launcher.cli validation run-dry --report-dir ./validation_reports/local
python -m linux_vhd_launcher.cli validation vm-status --runner manual
python -m linux_vhd_launcher.cli validation run-campaign --report-dir ./validation_reports/local
python -m linux_vhd_launcher.cli validation collect --report-dir ./validation_reports/local
python -m linux_vhd_launcher.cli validation render --report-dir ./validation_reports/local
python -m linux_vhd_launcher.cli validation status --report-dir ./validation_reports/local
python -m linux_vhd_launcher.cli validation bundle --report-dir ./validation_reports/local --redact --format zip
```

## Development

```bash
make lint
make typecheck
make test
bash scripts/smoke_arch.sh --offline --reuse-venv
```

## Windows VM validation docs

- Protocol: `docs/WINDOWS_VM_TEST_PROTOCOL.md`
- Report schema: `docs/VALIDATION_REPORT_SCHEMA.md`
- VM runner harness: `docs/VM_RUNNER.md`
- BCD mutation experiment: `docs/BCD_MUTATION_EXPERIMENT.md`
- BCD strategy boundaries: `docs/BCD_STRATEGY_MATRIX.md`
- Feasibility scope: `docs/FEASIBILITY.md`
- Virtdisk backend notes: `docs/VIRTDISK_BACKEND.md`
