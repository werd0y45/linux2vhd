# Validation Report Schema (v0.5)

## Current schema

- `schema_version`: `2`
- Status lifecycle is tracked per step and for overall campaign.

## Top-level fields

- `schema_version: int`
- `generated_at: str (ISO datetime)`
- `host: DoctorReport`
- `campaign_id: str`
- `vm_snapshot_name: str | null`
- `environment: CampaignEnvironment | null`
- `steps: ValidationStepResult[]`
- `artifacts: ValidationArtifact[]`
- `summary: ValidationSummary`
- `notes: str[]`
- `telemetry: TelemetryEvent[]`
- `errors: ErrorRecord[]`

## New v2 models

- `ProbeResult`
  - `id`, `name`, `status`, `value`, `details`, `source`, `command_preview`
- `CommandEvidence`
  - `command`, `exit_code`, `stdout_path`, `stderr_path`, `started_at`, `finished_at`, `duration_ms`
- `RollbackEvidence`
  - `planned`, `attempted`, `status`, `actions`, `errors`
- `BackendCapability`
  - `backend`, `capability`, `status`, `reason`, `docs_url`
- `CampaignEnvironment`
  - `machine_name`, `os_version`, `is_vm`, `hypervisor`, `secure_boot`, `bitlocker`, `is_admin`, `python_version`
- `TelemetryEvent`
  - `timestamp`, `level`, `component`, `event`, `message`, `context`
- `ErrorRecord`
  - `error_type`, `message`, `component`, `recoverable`, `suggested_action`, `original_exception`

## `ValidationStepResult` in v2

Each step includes:

- `id`, `title`, `status`, `error`, `docs_url`
- `command_evidence: CommandEvidence | null`
- `rollback_evidence: RollbackEvidence | null`
- `probes: ProbeResult[]`
- `capabilities: BackendCapability[]`

## Step statuses

- `pass`: step completed successfully.
- `fail`: step failed and requires inspection.
- `skip`: intentionally skipped.
- `blocked`: cannot proceed due to hard precondition.
- `not_run`: planned but not executed.

## Overall statuses

- `pass`: all executed steps passed.
- `fail`: at least one failed step.
- `blocked`: no failures, but at least one blocked step.
- `incomplete`: none of the above.

## Rollback statuses

- `not_needed`
- `pass`
- `fail`
- `partial`
- `not_run`

## Capability statuses

- `available`
- `unavailable`
- `unknown`
- `blocked`

## Probe statuses

- `pass`
- `fail`
- `warning`
- `unknown`
- `not_applicable`

## Migration from v1 to v2

Reader supports v1 payloads and migrates automatically:

1. `schema_version: 1` is accepted.
2. Legacy step fields (`started_at`, `finished_at`, `command_preview`, `stdout_path`, `stderr_path`, `rollback_status`) are mapped into `command_evidence`/`rollback_evidence`.
3. `probes`, `capabilities`, `telemetry`, `errors`, `environment` are initialized with safe defaults.
4. Artifact hashes are preserved as-is.

## Minimal v2 JSON example

```json
{
  "schema_version": 2,
  "generated_at": "2026-05-24T18:00:00+00:00",
  "host": {
    "os": "Linux",
    "python_version": "3.13.0",
    "is_windows": false,
    "is_admin": false,
    "pyqt6_available": true,
    "dry_run_available": true,
    "registry_path": "/tmp/vhd_registry.json",
    "config_path": "/tmp/config.json",
    "warnings": []
  },
  "campaign_id": "campaign-20260524-180000",
  "vm_snapshot_name": "pre-v05",
  "environment": null,
  "steps": [],
  "artifacts": [],
  "summary": {
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "blocked": 0,
    "overall_status": "incomplete"
  },
  "notes": [],
  "telemetry": [],
  "errors": []
}
```
