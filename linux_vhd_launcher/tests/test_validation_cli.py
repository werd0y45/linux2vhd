from __future__ import annotations

import json
from pathlib import Path

from linux_vhd_launcher import cli
from linux_vhd_launcher.models import ValidationReport


def test_validation_campaign_commands_on_linux(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    report_dir = tmp_path / "validation_run"

    assert cli.main(["validation", "init", "--report-dir", str(report_dir)]) == 0
    init_payload = json.loads(capsys.readouterr().out)
    assert init_payload["report_dir"] == str(report_dir)
    assert (report_dir / "report.json").exists()

    assert cli.main(["validation", "run-dry", "--report-dir", str(report_dir)]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert "overall_status" in run_payload

    assert cli.main(["validation", "capabilities", "--report-dir", str(report_dir), "--json"]) == 0
    capabilities_payload = json.loads(capsys.readouterr().out)
    assert "capabilities" in capabilities_payload
    assert "probes" in capabilities_payload

    assert cli.main(["validation", "collect", "--report-dir", str(report_dir)]) == 0
    collect_payload = json.loads(capsys.readouterr().out)
    assert collect_payload["artifacts"] >= 1

    assert cli.main(["validation", "render", "--report-dir", str(report_dir)]) == 0
    render_payload = json.loads(capsys.readouterr().out)
    assert Path(render_payload["report_markdown"]).exists()

    assert cli.main(["validation", "bundle", "--report-dir", str(report_dir), "--redact"]) == 0
    bundle_payload = json.loads(capsys.readouterr().out)
    assert Path(bundle_payload["bundle"]).exists()

    assert cli.main(["validation", "status", "--report-dir", str(report_dir)]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert "passed" in status_payload


def test_validation_windows_commands_are_gated(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    report_dir = tmp_path / "validation_run"
    assert cli.main(["validation", "init", "--report-dir", str(report_dir)]) == 0

    probe_code = cli.main(["validation", "windows-probe", "--report-dir", str(report_dir)])
    vhd_code = cli.main(["validation", "windows-vhd-smoke", "--report-dir", str(report_dir)])
    bcd_code = cli.main(
        ["validation", "windows-bcd-backup-smoke", "--report-dir", str(report_dir)]
    )
    mutation_code = cli.main(
        [
            "validation",
            "windows-bcd-mutation-smoke",
            "--report-dir",
            str(report_dir),
            "--lab-dir",
            str(report_dir / "lab"),
        ]
    )

    assert probe_code == 2
    assert vhd_code == 2
    assert bcd_code == 2
    assert mutation_code == 2


def test_linux_refuses_mutation_command(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(cli, "is_windows_platform", lambda: False)
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    report_dir = tmp_path / "validation_run"
    assert cli.main(["validation", "init", "--report-dir", str(report_dir)]) == 0
    code = cli.main(
        [
            "validation",
            "windows-bcd-mutation-smoke",
            "--report-dir",
            str(report_dir),
            "--lab-dir",
            str(report_dir / "lab"),
            "--execute-real-windows-ops",
            "--i-understand-this-is-experimental",
            "--confirm-vm-snapshot",
            "--no-dry-run",
        ]
    )
    assert code == 2


def test_validation_vm_status_and_run_campaign_safe_default(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    report_dir = tmp_path / "campaign"

    assert (
        cli.main(
            [
                "validation",
                "vm-status",
                "--runner",
                "manual",
                "--vm-name",
                "win11-lab",
            ]
        )
        == 0
    )
    vm_payload = json.loads(capsys.readouterr().out)
    assert vm_payload["runner"] == "manual"

    assert (
        cli.main(
            [
                "validation",
                "run-campaign",
                "--report-dir",
                str(report_dir),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert "overall_status" in payload

    report = ValidationReport.read_json(report_dir / "report.json")
    assert report.schema_version == 2
    assert any(step.id == "campaign-capabilities" for step in report.steps)
