"""Validation campaign helpers for v0.5."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tarfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from linux_vhd_launcher.errors import UnsafeRealOperationError, ValidationReportFormatError
from linux_vhd_launcher.models import (
    VALIDATION_REPORT_SCHEMA_VERSION,
    BackendCapability,
    CommandEvidence,
    DoctorReport,
    ErrorRecord,
    OperationPlan,
    ProbeResult,
    RollbackEvidence,
    TelemetryEvent,
    TelemetryLevel,
    ValidationArtifact,
    ValidationOverallStatus,
    ValidationReport,
    ValidationStepResult,
    ValidationStepStatus,
    ValidationSummary,
)
from linux_vhd_launcher.services.operation_planners import (
    BCD_DOCS_URL,
    VIRTDISK_DOCS_URL,
    build_windows_lab_plan,
)
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate

REPORT_FILE_NAME = "report.json"
VALIDATION_REPORTS_DIR_NAME = "validation_reports"


@dataclass(slots=True)
class StepExecutionResult:
    """Optional rich payload returned by step body."""

    payload: Any
    probes: list[ProbeResult] = field(default_factory=list)
    capabilities: list[BackendCapability] = field(default_factory=list)
    rollback_evidence: RollbackEvidence | None = None


class StepExecutionError(Exception):
    """Exception carrying structured step metadata on failure."""

    def __init__(
        self,
        message: str,
        *,
        rollback_evidence: RollbackEvidence | None = None,
        probes: list[ProbeResult] | None = None,
        capabilities: list[BackendCapability] | None = None,
    ) -> None:
        super().__init__(message)
        self.rollback_evidence = rollback_evidence
        self.probes = probes or []
        self.capabilities = capabilities or []


@dataclass(slots=True)
class BundleOptions:
    """Bundle export options."""

    redact: bool
    format: str


def create_report_directory(base_dir: Path) -> Path:
    """Create timestamped report directory under the given base directory."""
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report_dir = base_dir / VALIDATION_REPORTS_DIR_NAME / stamp
    report_dir.mkdir(parents=True, exist_ok=False)
    return report_dir


def report_path(report_dir: Path) -> Path:
    """Return path to report JSON file."""
    return report_dir / REPORT_FILE_NAME


def add_telemetry_event(
    report: ValidationReport,
    *,
    level: TelemetryLevel,
    component: str,
    event: str,
    message: str,
    context: dict[str, str | int | bool | None] | None = None,
) -> None:
    """Append telemetry event to report."""
    report.telemetry.append(
        TelemetryEvent(
            timestamp=datetime.now(UTC),
            level=level,
            component=component,
            event=event,
            message=message,
            context=context or {},
        )
    )


def add_error_record(
    report: ValidationReport,
    *,
    error_type: str,
    message: str,
    component: str,
    recoverable: bool,
    suggested_action: str | None,
    original_exception: str | None,
) -> None:
    """Append structured error record to report."""
    report.errors.append(
        ErrorRecord(
            error_type=error_type,
            message=message,
            component=component,
            recoverable=recoverable,
            suggested_action=suggested_action,
            original_exception=original_exception,
        )
    )


def create_initial_report(
    *,
    report_dir: Path,
    host: DoctorReport,
    campaign_id: str,
    vm_snapshot_name: str | None,
) -> ValidationReport:
    """Create and persist an initial empty report."""
    report = ValidationReport(
        schema_version=VALIDATION_REPORT_SCHEMA_VERSION,
        generated_at=datetime.now(UTC),
        host=host,
        campaign_id=campaign_id,
        vm_snapshot_name=vm_snapshot_name,
        steps=[],
        artifacts=[],
        summary=ValidationSummary(
            passed=0,
            failed=0,
            skipped=0,
            blocked=0,
            overall_status="incomplete",
        ),
        notes=[],
        telemetry=[],
        errors=[],
    )
    report.write_json(report_path(report_dir))
    add_telemetry_event(
        report,
        level="info",
        component="validation",
        event="report_initialized",
        message="Validation report initialized",
        context={"report_dir": str(report_dir), "campaign_id": campaign_id},
    )
    report.write_json(report_path(report_dir))
    return report


def load_report(report_dir: Path) -> ValidationReport:
    """Load report from disk."""
    path = report_path(report_dir)
    if not path.exists():
        raise ValidationReportFormatError(f"Validation report not found: {path}")
    return ValidationReport.read_json(path)


def save_report(report_dir: Path, report: ValidationReport) -> None:
    """Persist report JSON."""
    report.generated_at = datetime.now(UTC)
    report.summary = recompute_summary(report.steps)
    report.write_json(report_path(report_dir))


def recompute_summary(steps: list[ValidationStepResult]) -> ValidationSummary:
    """Compute aggregate summary from step statuses."""
    passed = sum(1 for step in steps if step.status == "pass")
    failed = sum(1 for step in steps if step.status == "fail")
    skipped = sum(1 for step in steps if step.status == "skip")
    blocked = sum(1 for step in steps if step.status == "blocked")

    if failed > 0:
        overall_status: ValidationOverallStatus = "fail"
    elif blocked > 0:
        overall_status = "blocked"
    elif steps and all(step.status == "pass" for step in steps):
        overall_status = "pass"
    else:
        overall_status = "incomplete"

    return ValidationSummary(
        passed=passed,
        failed=failed,
        skipped=skipped,
        blocked=blocked,
        overall_status=overall_status,
    )


def upsert_step(report: ValidationReport, step: ValidationStepResult) -> None:
    """Insert or replace step by id."""
    for idx, existing in enumerate(report.steps):
        if existing.id == step.id:
            report.steps[idx] = step
            return
    report.steps.append(step)


def add_or_replace_artifact(report: ValidationReport, artifact: ValidationArtifact) -> None:
    """Insert or replace artifact by kind+path key."""
    for idx, existing in enumerate(report.artifacts):
        if existing.kind == artifact.kind and existing.path == artifact.path:
            report.artifacts[idx] = artifact
            return
    report.artifacts.append(artifact)


def _render_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, indent=2)


def _step_payload(raw: Any) -> StepExecutionResult:
    if isinstance(raw, StepExecutionResult):
        return raw
    return StepExecutionResult(payload=raw)


def record_step(
    *,
    report: ValidationReport,
    report_dir: Path,
    step_id: str,
    title: str,
    command_preview: list[str] | None,
    docs_url: str | None,
    body: Callable[[], Any],
    component: str = "validation",
) -> ValidationStepResult:
    """Execute a step and write stdout/stderr artifact files."""
    started_at = datetime.now(UTC)
    add_telemetry_event(
        report,
        level="info",
        component=component,
        event="step_started",
        message=f"Step started: {step_id}",
        context={"step_id": step_id},
    )

    stdout_file = report_dir / "steps" / f"{step_id}.stdout.txt"
    stderr_file = report_dir / "steps" / f"{step_id}.stderr.txt"
    stdout_file.parent.mkdir(parents=True, exist_ok=True)

    status: ValidationStepStatus = "pass"
    error: str | None = None
    payload: StepExecutionResult = StepExecutionResult(payload={})

    try:
        payload = _step_payload(body())
    except StepExecutionError as exc:
        status = "fail"
        error = str(exc)
        payload = StepExecutionResult(
            payload={"error": str(exc)},
            probes=exc.probes,
            capabilities=exc.capabilities,
            rollback_evidence=exc.rollback_evidence,
        )
        add_error_record(
            report,
            error_type=type(exc).__name__,
            message=str(exc),
            component=component,
            recoverable=False,
            suggested_action="Inspect report errors and rollback evidence before proceeding.",
            original_exception=repr(exc),
        )
    except Exception as exc:  # noqa: BLE001
        status = "fail"
        error = str(exc)
        add_error_record(
            report,
            error_type=type(exc).__name__,
            message=str(exc),
            component=component,
            recoverable=False,
            suggested_action="Inspect report errors and rollback evidence before proceeding.",
            original_exception=repr(exc),
        )

    if status == "pass":
        stdout_text = _render_payload(payload.payload)
        stdout_file.write_text(stdout_text + "\n", encoding="utf-8")
        if stderr_file.exists():
            stderr_file.unlink(missing_ok=True)
    else:
        stderr_file.write_text((error or "unknown error") + "\n", encoding="utf-8")
        if stdout_file.exists():
            stdout_file.unlink(missing_ok=True)

    finished_at = datetime.now(UTC)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    command_evidence = CommandEvidence(
        command=list(command_preview or []),
        exit_code=0 if status == "pass" else 1,
        stdout_path=stdout_file if stdout_file.exists() else None,
        stderr_path=stderr_file if stderr_file.exists() else None,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )

    result = ValidationStepResult(
        id=step_id,
        title=title,
        status=status,
        error=error,
        docs_url=docs_url,
        command_evidence=command_evidence,
        rollback_evidence=payload.rollback_evidence,
        probes=payload.probes,
        capabilities=payload.capabilities,
    )
    upsert_step(report, result)

    add_telemetry_event(
        report,
        level="info" if status == "pass" else "error",
        component=component,
        event="step_finished",
        message=f"Step finished: {step_id}",
        context={"step_id": step_id, "status": status, "duration_ms": duration_ms},
    )
    return result


def run_dry_campaign(
    *,
    report_dir: Path,
    report: ValidationReport,
    doctor_payload: dict[str, Any],
    installer_plan_factory: Callable[[Path, Path, int, str], OperationPlan],
    registry_reader: Callable[[], list[dict[str, Any]]],
    gate: RealWindowsOpsGate,
) -> None:
    """Run Linux-safe dry validation checks and update report."""

    dry_iso = report_dir / "dry_run_input.iso"
    dry_iso.write_bytes(b"iso")
    dry_vhd = report_dir / "dry_run_test.vhdx"

    record_step(
        report=report,
        report_dir=report_dir,
        step_id="dry-doctor",
        title="doctor",
        command_preview=["linux-vhd-launcher", "doctor", "--json"],
        docs_url=None,
        body=lambda: doctor_payload,
    )

    def _plan_install_body() -> dict[str, Any]:
        plan = installer_plan_factory(dry_iso, dry_vhd, 20, "vhdx")
        payload = plan.to_dict()
        plan_path = report_dir / "artifacts" / "plan_install_dry_run.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        add_or_replace_artifact(
            report,
            ValidationArtifact(
                kind="operation_plan",
                path=plan_path,
                sha256=compute_sha256(plan_path),
                description="OperationPlan from plan-install --dry-run --json",
            ),
        )
        return payload

    record_step(
        report=report,
        report_dir=report_dir,
        step_id="dry-plan-install",
        title="plan-install --dry-run",
        command_preview=[
            "linux-vhd-launcher",
            "plan-install",
            "--dry-run",
            "--json",
        ],
        docs_url=VIRTDISK_DOCS_URL,
        body=_plan_install_body,
    )

    def _plan_lab_body() -> dict[str, Any]:
        plan = build_windows_lab_plan()
        payload = plan.to_dict()
        plan_path = report_dir / "artifacts" / "plan_windows_lab.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        add_or_replace_artifact(
            report,
            ValidationArtifact(
                kind="operation_plan",
                path=plan_path,
                sha256=compute_sha256(plan_path),
                description="OperationPlan from plan-windows-lab --json",
            ),
        )
        return payload

    record_step(
        report=report,
        report_dir=report_dir,
        step_id="dry-plan-windows-lab",
        title="plan-windows-lab",
        command_preview=["linux-vhd-launcher", "plan-windows-lab", "--json"],
        docs_url=BCD_DOCS_URL,
        body=_plan_lab_body,
    )

    record_step(
        report=report,
        report_dir=report_dir,
        step_id="dry-registry-read",
        title="registry read",
        command_preview=["linux-vhd-launcher", "show-registry"],
        docs_url=None,
        body=registry_reader,
    )

    def _gate_check_body() -> dict[str, str]:
        try:
            gate.assert_allowed(
                operation="validation dry safety probe",
                rollback_plan="dummy rollback",
                report_path=report_path(report_dir),
                target_path=report_dir / "outside" / "dummy.vhdx",
                require_rollback_plan=True,
                require_report=True,
                require_target_in_lab_dir=True,
            )
        except UnsafeRealOperationError as exc:
            return {
                "result": "pass",
                "reason": str(exc),
            }
        raise ValidationReportFormatError(
            "Safety gate unexpectedly allowed a real operation in run-dry mode."
        )

    record_step(
        report=report,
        report_dir=report_dir,
        step_id="dry-backend-safety-gate",
        title="backend safety gate check",
        command_preview=["linux-vhd-launcher", "validation", "run-dry"],
        docs_url=None,
        body=_gate_check_body,
    )


def collect_artifacts(report_dir: Path, report: ValidationReport) -> None:
    """Collect and hash configured artifacts into report directory."""
    artifacts_dir = report_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    sources: list[tuple[str, Path, str]] = []

    host_registry = Path(report.host.registry_path)
    host_config = Path(report.host.config_path)

    if host_registry.exists():
        sources.append(("registry", host_registry, "Application registry JSON"))
    else:
        report.notes.append(f"Registry file missing: {host_registry}")

    if host_config.exists():
        sources.append(("config", host_config, "Application config JSON"))
    else:
        report.notes.append(f"Config file missing: {host_config}")

    for doctor_name in ["doctor_initial.json", "doctor_run_dry.json", "doctor.json"]:
        doctor_path = report_dir / doctor_name
        if doctor_path.exists():
            sources.append(("doctor_json", doctor_path, f"Doctor payload ({doctor_name})"))

    for plan_name in ["plan_install_dry_run.json", "plan_windows_lab.json"]:
        plan_path = artifacts_dir / plan_name
        if plan_path.exists():
            sources.append(("operation_plan", plan_path, f"OperationPlan ({plan_name})"))

    app_log = report_dir / "app.log"
    if app_log.exists():
        sources.append(("app_log", app_log, "Validation app log"))

    for kind, source_path, description in sources:
        if source_path.exists() and source_path.parent != artifacts_dir:
            target_path = artifacts_dir / source_path.name
            shutil.copy2(source_path, target_path)
        else:
            target_path = source_path

        sha = compute_sha256(target_path) if target_path.exists() else None
        add_or_replace_artifact(
            report,
            ValidationArtifact(
                kind=kind,
                path=target_path,
                sha256=sha,
                description=description,
            ),
        )

    for step in report.steps:
        if step.command_evidence is None:
            continue
        for evidence_path in [step.command_evidence.stdout_path, step.command_evidence.stderr_path]:
            if evidence_path and evidence_path.exists():
                add_or_replace_artifact(
                    report,
                    ValidationArtifact(
                        kind="step_evidence",
                        path=evidence_path,
                        sha256=compute_sha256(evidence_path),
                        description=f"Step evidence for {step.id}",
                    ),
                )


def compute_sha256(path: Path) -> str:
    """Compute file SHA-256 in streaming mode."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_markdown(report: ValidationReport) -> str:
    """Render report to human-readable markdown."""
    lines = [
        "# LinuxVHDLauncher Validation Report",
        "",
        f"- Campaign ID: `{report.campaign_id}`",
        f"- Schema version: `{report.schema_version}`",
        f"- Generated at: `{report.generated_at.isoformat()}`",
        f"- VM snapshot: `{report.vm_snapshot_name}`",
        f"- Overall status: `{report.summary.overall_status}`",
        "",
        "## Summary",
        "",
        f"- Passed: {report.summary.passed}",
        f"- Failed: {report.summary.failed}",
        f"- Skipped: {report.summary.skipped}",
        f"- Blocked: {report.summary.blocked}",
        "",
        "## Steps",
        "",
    ]

    for step in report.steps:
        lines.append(f"### {step.id} - {step.title}")
        lines.append(f"- Status: `{step.status}`")
        if step.command_evidence:
            started = (
                step.command_evidence.started_at.isoformat()
                if step.command_evidence.started_at
                else None
            )
            finished = (
                step.command_evidence.finished_at.isoformat()
                if step.command_evidence.finished_at
                else None
            )
            lines.append(f"- Started: `{started}`")
            lines.append(f"- Finished: `{finished}`")
            if step.command_evidence.command:
                lines.append(f"- Command preview: `{ ' '.join(step.command_evidence.command) }`")
            if step.command_evidence.stdout_path:
                lines.append(f"- stdout: `{step.command_evidence.stdout_path}`")
            if step.command_evidence.stderr_path:
                lines.append(f"- stderr: `{step.command_evidence.stderr_path}`")
            lines.append(f"- Exit code: `{step.command_evidence.exit_code}`")
            lines.append(f"- Duration ms: `{step.command_evidence.duration_ms}`")

        if step.rollback_evidence:
            lines.append(f"- Rollback status: `{step.rollback_evidence.status}`")
            if step.rollback_evidence.actions:
                lines.append("- Rollback actions:")
                for action in step.rollback_evidence.actions:
                    lines.append(f"  - {action}")
            if step.rollback_evidence.errors:
                lines.append("- Rollback errors:")
                for entry in step.rollback_evidence.errors:
                    lines.append(f"  - {entry}")

        if step.probes:
            lines.append("- Probes:")
            for probe in step.probes:
                lines.append(
                    f"  - {probe.id}: status={probe.status} value={probe.value} details={probe.details}"
                )

        if step.capabilities:
            lines.append("- Capabilities:")
            for capability in step.capabilities:
                lines.append(
                    f"  - {capability.backend}/{capability.capability}: {capability.status}"
                )

        if step.error:
            lines.append(f"- Error: `{step.error}`")
        if step.docs_url:
            lines.append(f"- Docs: {step.docs_url}")
        lines.append("")

    lines.extend(["## Artifacts", ""])
    for artifact in report.artifacts:
        lines.append(f"- `{artifact.kind}`: `{artifact.path}`")
        lines.append(f"  - sha256: `{artifact.sha256}`")
        lines.append(f"  - {artifact.description}")

    if report.errors:
        lines.extend(["", "## Errors", ""])
        for error in report.errors:
            lines.append(
                f"- [{error.component}] {error.error_type}: {error.message} "
                f"(recoverable={error.recoverable})"
            )
            if error.suggested_action:
                lines.append(f"  - suggested_action: {error.suggested_action}")

    if report.notes:
        lines.extend(["", "## Notes", ""])
        for note in report.notes:
            lines.append(f"- {note}")

    return "\n".join(lines) + "\n"


def _redact_text(content: str, *, redact_machine_name: bool, machine_name: str | None) -> str:
    content = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<redacted-email>", content)
    content = re.sub(r"(/home/)([^/\s]+)", r"\1<redacted-user>", content)
    content = re.sub(r"(C:\\\\Users\\\\)([^\\\\\"/\s]+)", r"\1<redacted-user>", content)
    if redact_machine_name and machine_name:
        content = content.replace(machine_name, "<redacted-machine>")
    return content


def _copy_or_redact_file(
    src: Path,
    dst: Path,
    *,
    redact: bool,
    redact_machine_name: bool,
    machine_name: str | None,
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not redact:
        shutil.copy2(src, dst)
        return

    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        shutil.copy2(src, dst)
        return

    dst.write_text(
        _redact_text(text, redact_machine_name=redact_machine_name, machine_name=machine_name),
        encoding="utf-8",
    )


def create_artifact_bundle(
    *,
    report_dir: Path,
    report: ValidationReport,
    options: BundleOptions,
) -> Path:
    """Create bundle with report artifacts and checksums."""
    staging = report_dir / "bundle_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)

    include_files: list[Path] = []

    def _include(path: Path, rel: Path) -> None:
        if not path.exists():
            return
        target = staging / rel
        _copy_or_redact_file(
            path,
            target,
            redact=options.redact,
            redact_machine_name=options.redact,
            machine_name=report.environment.machine_name if report.environment else None,
        )
        include_files.append(target)

    _include(report_path(report_dir), Path("report.json"))
    _include(report_dir / "report.md", Path("report.md"))
    _include(report_dir / "doctor.json", Path("doctor.json"))
    _include(report_dir / "doctor_initial.json", Path("doctor_initial.json"))
    _include(report_dir / "doctor_run_dry.json", Path("doctor_run_dry.json"))

    artifacts_dir = report_dir / "artifacts"
    if artifacts_dir.exists():
        for path in artifacts_dir.rglob("*"):
            if path.is_file():
                _include(path, Path("artifacts") / path.relative_to(artifacts_dir))

    steps_dir = report_dir / "steps"
    if steps_dir.exists():
        for path in steps_dir.rglob("*"):
            if path.is_file():
                _include(path, Path("steps") / path.relative_to(steps_dir))

    config_path = Path(report.host.config_path)
    registry_path = Path(report.host.registry_path)
    _include(config_path, Path("config_snapshot") / config_path.name)
    _include(registry_path, Path("registry_snapshot") / registry_path.name)

    checksums: dict[str, str] = {}
    for file_path in include_files:
        checksums[str(file_path.relative_to(staging))] = compute_sha256(file_path)

    checksums_path = staging / "checksums.json"
    checksums_path.write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")

    bundle_ext = "zip" if options.format == "zip" else "tar.gz"
    bundle_path = report_dir / f"validation_bundle.{bundle_ext}"

    if options.format == "zip":
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_archive:
            for file_path in staging.rglob("*"):
                if file_path.is_file():
                    zip_archive.write(file_path, arcname=file_path.relative_to(staging))
    else:
        with tarfile.open(bundle_path, "w:gz") as tar_archive:
            for file_path in staging.rglob("*"):
                tar_archive.add(file_path, arcname=file_path.relative_to(staging))

    add_or_replace_artifact(
        report,
        ValidationArtifact(
            kind="bundle",
            path=bundle_path,
            sha256=compute_sha256(bundle_path),
            description="Validation artifact bundle",
        ),
    )

    return bundle_path
