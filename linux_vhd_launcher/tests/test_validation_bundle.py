from __future__ import annotations

import json
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from linux_vhd_launcher.models import DoctorReport, ValidationReport, ValidationSummary
from linux_vhd_launcher.validation import BundleOptions, create_artifact_bundle


def _report(tmp_path: Path) -> ValidationReport:
    return ValidationReport(
        schema_version=2,
        generated_at=datetime.now(UTC),
        host=DoctorReport(
            os="Linux",
            python_version="3.12.0",
            is_windows=False,
            is_admin=False,
            pyqt6_available=True,
            dry_run_available=True,
            registry_path=str(tmp_path / "cfg" / "registry.json"),
            config_path=str(tmp_path / "cfg" / "config.json"),
            warnings=[],
        ),
        campaign_id="c1",
        vm_snapshot_name=None,
        steps=[],
        artifacts=[],
        summary=ValidationSummary(0, 0, 0, 0, "incomplete"),
        notes=[],
    )


def test_bundle_created_with_checksums_zip(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir(parents=True)
    report = _report(tmp_path)
    (report_dir / "report.json").write_text(report.to_json(), encoding="utf-8")
    (report_dir / "report.md").write_text("# report\n", encoding="utf-8")

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text('{"email":"a@b.com"}\n', encoding="utf-8")
    (cfg_dir / "registry.json").write_text('{"path":"/home/user/x"}\n', encoding="utf-8")

    bundle_path = create_artifact_bundle(
        report_dir=report_dir,
        report=report,
        options=BundleOptions(redact=False, format="zip"),
    )

    assert bundle_path.exists()
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
    assert "checksums.json" in names


def test_bundle_redaction_and_targz(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir(parents=True)
    report = _report(tmp_path)
    (report_dir / "report.json").write_text(report.to_json(), encoding="utf-8")

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(
        '{"owner":"C:\\\\Users\\\\Alice","email":"alice@example.com"}\n',
        encoding="utf-8",
    )
    (cfg_dir / "registry.json").write_text('{"home":"/home/alice/project"}\n', encoding="utf-8")

    bundle_path = create_artifact_bundle(
        report_dir=report_dir,
        report=report,
        options=BundleOptions(redact=True, format="targz"),
    )
    assert bundle_path.exists()

    with tarfile.open(bundle_path, "r:gz") as tf:
        cfg_member = tf.extractfile("config_snapshot/config.json")
        assert cfg_member is not None
        content = cfg_member.read().decode("utf-8")
        assert "<redacted-email>" in content
        assert "<redacted-user>" in content


def test_bundle_missing_optional_artifacts_tolerated(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir(parents=True)
    report = _report(tmp_path)
    (report_dir / "report.json").write_text(report.to_json(), encoding="utf-8")

    bundle_path = create_artifact_bundle(
        report_dir=report_dir,
        report=report,
        options=BundleOptions(redact=False, format="zip"),
    )

    with zipfile.ZipFile(bundle_path) as zf:
        checksums = json.loads(zf.read("checksums.json").decode("utf-8"))
    assert isinstance(checksums, dict)
