from __future__ import annotations

import json
from pathlib import Path

import pytest

from linux_vhd_launcher import cli
from linux_vhd_launcher.errors import UnsupportedPlatformError
from linux_vhd_launcher.models import BcdApplicationTypeProbe, BcdProbeReport
from linux_vhd_launcher.services import bcd_probe
from linux_vhd_launcher.services.bcd_probe import BcdProbeOutcome, probe_bcd_application_types
from linux_vhd_launcher.system.runner import CommandResult


def test_bcd_probe_uses_offline_store_and_records_results(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    lab_dir = tmp_path / "lab"
    report_dir = tmp_path / "reports"

    class FakeRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(self, command: list[str], *, elevated_required: bool = False, check: bool = True) -> CommandResult:
            del elevated_required
            del check
            self.commands.append(command)
            if command[:2] == ["bcdedit", "/createstore"]:
                return CommandResult(tuple(command), 0, "store created", "")
            if command[:3] == ["bcdedit", "/?", "create"]:
                return CommandResult(tuple(command), 0, "create help", "")
            if "/application" in command:
                app_type = command[-1]
                if app_type == "bootsector":
                    return CommandResult(tuple(command), 1, "", "invalid")
                return CommandResult(
                    tuple(command),
                    0,
                    f"The entry was successfully created {{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}} {app_type}",
                    "",
                )
            if command[:3] == ["bcdedit", "/store", str(lab_dir / "bcd_probe" / "bcd_probe.bcd")]:
                return CommandResult(tuple(command), 0, "enum output", "")
            return CommandResult(tuple(command), 0, "", "")

    fake_runner = FakeRunner()
    monkeypatch.setattr(bcd_probe, "is_windows_platform", lambda: True)

    outcome = probe_bcd_application_types(
        lab_dir=lab_dir,
        report_dir=report_dir,
        runner=fake_runner,  # type: ignore[arg-type]
    )

    create_commands = [cmd for cmd in fake_runner.commands if "/application" in cmd]
    assert create_commands
    expected_store = str(lab_dir / "bcd_probe" / "bcd_probe.bcd")
    for command in create_commands:
        assert "/store" in command
        assert expected_store in command
        assert command[0] == "bcdedit"

    assert all(command[:2] != ["bcdedit", "/create"] for command in create_commands)

    probes = {item.application_type: item for item in outcome.report.probes}
    assert probes["osloader"].supported is True
    assert probes["osloader"].guid == "{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}"
    assert probes["bootsector"].supported is False
    assert "bootapp" in outcome.report.supported_types

    assert outcome.report.enum_output_path.exists()
    assert outcome.report.enum_output_path.read_text(encoding="utf-8") == "enum output"
    assert outcome.enum_stderr_path.exists()
    assert outcome.report_path.exists()


def test_bcd_probe_refuses_non_windows(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(bcd_probe, "is_windows_platform", lambda: False)
    with pytest.raises(UnsupportedPlatformError):
        probe_bcd_application_types(lab_dir=tmp_path / "lab", report_dir=tmp_path / "reports")


def test_cli_demo_bcd_probe_json(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))

    def _fake_probe(*, lab_dir: Path, report_dir: Path) -> BcdProbeOutcome:
        report_dir.mkdir(parents=True, exist_ok=True)
        probe = BcdApplicationTypeProbe(
            application_type="bootapp",
            supported=True,
            guid="{bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb}",
            command=["bcdedit", "/store", "x", "/create", "/application", "bootapp"],
            returncode=0,
            stdout="ok",
            stderr="",
            notes=None,
        )
        report = BcdProbeReport(
            store_path=lab_dir / "bcd_probe" / "bcd_probe.bcd",
            probes=[probe],
            enum_output_path=report_dir / "bcd_probe_enum_all_v.txt",
            supported_types=["bootapp"],
            blocked_reason=None,
        )
        report.enum_output_path.write_text("enum", encoding="utf-8")
        stderr_path = report_dir / "bcd_probe_enum_all_v.stderr.txt"
        stderr_path.write_text("", encoding="utf-8")
        report_path = report_dir / "bcd_application_type_probe.json"
        report_path.write_text(json.dumps({"report": report.to_dict()}), encoding="utf-8")
        return BcdProbeOutcome(report=report, report_path=report_path, enum_stderr_path=stderr_path)

    monkeypatch.setattr(cli, "probe_bcd_application_types", _fake_probe)

    code = cli.main(
        [
            "demo",
            "bcd",
            "probe-application-types",
            "--lab-dir",
            str(tmp_path / "lab"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["supported_types"] == ["bootapp"]
