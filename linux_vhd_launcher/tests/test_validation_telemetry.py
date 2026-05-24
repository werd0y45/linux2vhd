from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from linux_vhd_launcher.models import (
    DoctorReport,
    TelemetryEvent,
    ValidationReport,
    ValidationSummary,
)
from linux_vhd_launcher.validation import (
    add_error_record,
    add_telemetry_event,
    create_initial_report,
    save_report,
)


def _doctor() -> DoctorReport:
    return DoctorReport(
        os="Linux",
        python_version="3.12",
        is_windows=False,
        is_admin=False,
        pyqt6_available=True,
        dry_run_available=True,
        registry_path="/tmp/registry.json",
        config_path="/tmp/config.json",
        warnings=[],
    )


def test_telemetry_event_serialization_roundtrip() -> None:
    event = TelemetryEvent(
        timestamp=datetime.now(UTC),
        level="info",
        component="validation",
        event="x",
        message="ok",
        context={"flag": True, "n": 1, "txt": "v", "none": None},
    )
    loaded = TelemetryEvent.from_dict(event.to_dict())
    assert loaded.component == "validation"
    assert loaded.context["flag"] is True


def test_error_records_written_to_report(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir(parents=True)
    report = create_initial_report(
        report_dir=report_dir,
        host=_doctor(),
        campaign_id="campaign",
        vm_snapshot_name=None,
    )
    add_telemetry_event(
        report,
        level="warning",
        component="tests",
        event="t1",
        message="telemetry",
        context={"k": "v"},
    )
    add_error_record(
        report,
        error_type="ExampleError",
        message="failed",
        component="tests",
        recoverable=False,
        suggested_action="inspect",
        original_exception="RuntimeError('x')",
    )
    save_report(report_dir, report)

    loaded = ValidationReport.read_json(report_dir / "report.json")
    assert loaded.errors
    assert loaded.errors[0].error_type == "ExampleError"
    assert loaded.telemetry
    assert loaded.telemetry[-1].event == "t1"


def test_validation_summary_survives_with_no_steps(tmp_path: Path) -> None:
    report = ValidationReport(
        schema_version=2,
        generated_at=datetime.now(UTC),
        host=_doctor(),
        campaign_id="c",
        vm_snapshot_name=None,
        steps=[],
        artifacts=[],
        summary=ValidationSummary(0, 0, 0, 0, "incomplete"),
        notes=[],
    )
    target = tmp_path / "r.json"
    report.write_json(target)
    loaded = ValidationReport.read_json(target)
    assert loaded.summary.overall_status == "incomplete"
