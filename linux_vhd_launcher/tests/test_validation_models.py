from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from linux_vhd_launcher.errors import ValidationReportFormatError
from linux_vhd_launcher.models import (
    VALIDATION_REPORT_SCHEMA_VERSION,
    CampaignEnvironment,
    CommandEvidence,
    DoctorReport,
    ErrorRecord,
    ProbeResult,
    RollbackEvidence,
    TelemetryEvent,
    ValidationArtifact,
    ValidationReport,
    ValidationStepResult,
    ValidationSummary,
)


def _sample_report() -> ValidationReport:
    return ValidationReport(
        schema_version=VALIDATION_REPORT_SCHEMA_VERSION,
        generated_at=datetime.now(UTC),
        host=DoctorReport(
            os="Linux",
            python_version="3.12.0",
            is_windows=False,
            is_admin=False,
            pyqt6_available=True,
            dry_run_available=True,
            registry_path="/tmp/registry.json",
            config_path="/tmp/config.json",
            warnings=["w1"],
        ),
        campaign_id="campaign-1",
        vm_snapshot_name=None,
        steps=[
            ValidationStepResult(
                id="s1",
                title="step",
                status="pass",
                error=None,
                docs_url="https://example.invalid",
                command_evidence=CommandEvidence(
                    command=["echo", "ok"],
                    exit_code=0,
                    stdout_path=Path("/tmp/stdout"),
                    stderr_path=None,
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                    duration_ms=1,
                ),
                rollback_evidence=RollbackEvidence(
                    planned=True,
                    attempted=True,
                    status="pass",
                    actions=["cleanup"],
                    errors=[],
                ),
                probes=[
                    ProbeResult(
                        id="probe-1",
                        name="probe",
                        status="pass",
                        value=True,
                        details=None,
                        source="test",
                        command_preview=["echo", "x"],
                    )
                ],
                capabilities=[],
            )
        ],
        artifacts=[
            ValidationArtifact(
                kind="doctor_json",
                path=Path("/tmp/doctor.json"),
                sha256="abc",
                description="doctor",
            )
        ],
        summary=ValidationSummary(
            passed=1,
            failed=0,
            skipped=0,
            blocked=0,
            overall_status="pass",
        ),
        notes=["note"],
        environment=CampaignEnvironment(
            machine_name="vm-01",
            os_version="Windows 11",
            is_vm=True,
            hypervisor="Hyper-V",
            secure_boot="On",
            bitlocker="Off",
            is_admin=True,
            python_version="3.12.0",
        ),
        telemetry=[
            TelemetryEvent(
                timestamp=datetime.now(UTC),
                level="info",
                component="validation",
                event="event",
                message="ok",
                context={"k": "v"},
            )
        ],
        errors=[
            ErrorRecord(
                error_type="ExampleError",
                message="none",
                component="tests",
                recoverable=True,
                suggested_action=None,
                original_exception=None,
            )
        ],
    )


def _sample_v1_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "host": {
            "os": "Linux",
            "python_version": "3.12.0",
            "is_windows": False,
            "is_admin": False,
            "pyqt6_available": True,
            "dry_run_available": True,
            "registry_path": "/tmp/registry.json",
            "config_path": "/tmp/config.json",
            "warnings": [],
        },
        "campaign_id": "campaign-v1",
        "vm_snapshot_name": None,
        "steps": [
            {
                "id": "s1",
                "title": "legacy",
                "status": "pass",
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": datetime.now(UTC).isoformat(),
                "command_preview": ["echo", "legacy"],
                "stdout_path": "/tmp/stdout",
                "stderr_path": None,
                "error": None,
                "rollback_status": None,
                "docs_url": None,
            }
        ],
        "artifacts": [
            {
                "kind": "doctor_json",
                "path": "/tmp/doctor.json",
                "sha256": "legacy-hash",
                "description": "legacy doctor",
            }
        ],
        "summary": {
            "passed": 1,
            "failed": 0,
            "skipped": 0,
            "blocked": 0,
            "overall_status": "pass",
        },
        "notes": [],
    }


def test_validation_report_v2_roundtrip() -> None:
    report = _sample_report()
    loaded = ValidationReport.from_json(report.to_json())

    assert loaded.schema_version == VALIDATION_REPORT_SCHEMA_VERSION
    assert loaded.campaign_id == report.campaign_id
    assert loaded.steps[0].status == "pass"
    assert loaded.steps[0].command_evidence is not None
    assert loaded.artifacts[0].kind == "doctor_json"
    assert loaded.telemetry


def test_validation_report_v1_migration() -> None:
    loaded = ValidationReport.from_dict(_sample_v1_payload())

    assert loaded.schema_version == 2
    assert loaded.campaign_id == "campaign-v1"
    assert loaded.steps[0].command_evidence is not None
    assert loaded.steps[0].command_evidence.command == ["echo", "legacy"]


def test_validation_report_corrupted_json() -> None:
    with pytest.raises(ValidationReportFormatError):
        ValidationReport.from_json("{bad json")


def test_validation_report_unsupported_future_schema() -> None:
    report = _sample_report().to_dict()
    report["schema_version"] = VALIDATION_REPORT_SCHEMA_VERSION + 1

    with pytest.raises(ValidationReportFormatError):
        ValidationReport.from_dict(report)


def test_validation_report_missing_optional_fields() -> None:
    payload = _sample_report().to_dict()
    payload.pop("environment", None)
    payload.pop("telemetry", None)
    payload.pop("errors", None)
    steps = payload["steps"]
    assert isinstance(steps, list)
    assert isinstance(steps[0], dict)
    steps[0].pop("rollback_evidence", None)
    steps[0].pop("probes", None)
    steps[0].pop("capabilities", None)

    loaded = ValidationReport.from_dict(payload)
    assert loaded.environment is None
    assert loaded.errors == []
    assert loaded.steps[0].rollback_evidence is None


def test_validation_report_artifact_hash_preserved() -> None:
    report = _sample_report()
    loaded = ValidationReport.from_json(report.to_json())

    assert loaded.artifacts[0].sha256 == "abc"


def test_validation_report_missing_required_fields() -> None:
    payload = {
        "schema_version": VALIDATION_REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    with pytest.raises(ValidationReportFormatError):
        ValidationReport.from_dict(payload)


def test_validation_report_invalid_step_status() -> None:
    report = _sample_report().to_dict()
    steps = report["steps"]
    assert isinstance(steps, list)
    first = steps[0]
    assert isinstance(first, dict)
    first["status"] = "unknown"

    with pytest.raises(ValidationReportFormatError):
        ValidationReport.from_dict(report)


def test_validation_report_read_write_file_roundtrip(tmp_path: Path) -> None:
    report = _sample_report()
    target = tmp_path / "report.json"
    report.write_json(target)
    loaded = ValidationReport.read_json(target)

    assert loaded.campaign_id == report.campaign_id
