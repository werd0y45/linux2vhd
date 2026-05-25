from __future__ import annotations

import json
from pathlib import Path

import pytest

from linux_vhd_launcher import cli
from linux_vhd_launcher.errors import UnsupportedPlatformError
from linux_vhd_launcher.models import (
    BcdApplicationTypeProbe,
    BcdBootappElementProbeReport,
    BcdBootappVhdDeviceProbeReport,
    BcdElementSetProbe,
    BcdProbeReport,
)
from linux_vhd_launcher.services import bcd_probe
from linux_vhd_launcher.services.bcd_probe import (
    BcdBootappElementProbeOutcome,
    BcdBootappVhdDeviceProbeOutcome,
    BcdProbeOutcome,
    analyze_bcd_bootapp_probe_report,
    analyze_bcd_bootapp_vhd_device_probe_report,
    probe_bcd_application_types,
    probe_bcd_bootapp_elements,
    probe_bcd_bootapp_vhd_device,
)
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


def test_bootapp_element_probe_uses_store_and_reports_supported(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
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
            if "/create" in command and "/application" in command:
                return CommandResult(
                    tuple(command),
                    0,
                    "The entry was successfully created {11111111-1111-1111-1111-111111111111}",
                    "",
                )
            if "/set" in command:
                return CommandResult(tuple(command), 0, "ok", "")
            if "/enum" in command:
                return CommandResult(tuple(command), 0, "enum output", "")
            return CommandResult(tuple(command), 0, "", "")

    fake_runner = FakeRunner()
    monkeypatch.setattr(bcd_probe, "is_windows_platform", lambda: True)
    outcome = probe_bcd_bootapp_elements(
        lab_dir=lab_dir,
        report_dir=report_dir,
        runner=fake_runner,  # type: ignore[arg-type]
    )

    assert outcome.report.bootapp_guid == "{11111111-1111-1111-1111-111111111111}"
    assert outcome.report.create_supported is True
    assert outcome.report.conclusion == "bootapp_elements_supported"
    assert all(command[0] == "bcdedit" for command in fake_runner.commands)
    for command in fake_runner.commands:
        if "/set" in command or "/create" in command:
            assert "/store" in command
            assert str(lab_dir / "bcd_probe" / "bootapp_elements_probe.bcd") in command
    assert all("{bootmgr}" not in " ".join(command) for command in fake_runner.commands)


def test_bootapp_element_probe_reports_create_only_when_path_rejected(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    class FakeRunner:
        def run(self, command: list[str], *, elevated_required: bool = False, check: bool = True) -> CommandResult:
            del elevated_required
            del check
            if command[:2] == ["bcdedit", "/createstore"]:
                return CommandResult(tuple(command), 0, "store created", "")
            if "/create" in command and "/application" in command:
                return CommandResult(
                    tuple(command),
                    0,
                    "The entry was successfully created {22222222-2222-2222-2222-222222222222}",
                    "",
                )
            if "/set" in command and "path" in command:
                return CommandResult(tuple(command), 1, "", "element not valid")
            if "/set" in command:
                return CommandResult(tuple(command), 0, "ok", "")
            if "/enum" in command:
                return CommandResult(tuple(command), 0, "enum output", "")
            return CommandResult(tuple(command), 0, "", "")

    monkeypatch.setattr(bcd_probe, "is_windows_platform", lambda: True)
    outcome = probe_bcd_bootapp_elements(
        lab_dir=tmp_path / "lab",
        report_dir=tmp_path / "reports",
        runner=FakeRunner(),  # type: ignore[arg-type]
    )
    assert outcome.report.create_supported is True
    assert outcome.report.conclusion == "bootapp_create_only"
    path_probe = next(item for item in outcome.report.element_probes if item.element == "path")
    assert path_probe.supported is False


def test_analyze_bootapp_probe_recommends_strategy(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = BcdBootappElementProbeReport(
        store_path=tmp_path / "lab" / "bcd_probe" / "bootapp_elements_probe.bcd",
        bootapp_guid="{33333333-3333-3333-3333-333333333333}",
        create_supported=True,
        element_probes=[
            BcdElementSetProbe(
                element="device",
                value="partition=C:",
                supported=True,
                command=["bcdedit", "/store", "x", "/set", "{GUID}", "device", "partition=C:"],
                returncode=0,
                stdout="ok",
                stderr="",
                notes=None,
            ),
            BcdElementSetProbe(
                element="path",
                value="\\EFI\\LinuxVHDLauncher\\ubuntu-live\\BOOTX64.EFI",
                supported=True,
                command=["bcdedit", "/store", "x", "/set", "{GUID}", "path", "\\EFI\\LinuxVHDLauncher\\ubuntu-live\\BOOTX64.EFI"],
                returncode=0,
                stdout="ok",
                stderr="",
                notes=None,
            ),
        ],
        enum_output_path=report_dir / "bcd_bootapp_elements_enum_all_v.txt",
        conclusion="bootapp_elements_supported",
        warnings=[],
        blockers=[],
    )
    probe_path = report_dir / "bcd_bootapp_elements_probe.json"
    probe_path.write_text(json.dumps({"report": report.to_dict()}), encoding="utf-8")

    analysis = analyze_bcd_bootapp_probe_report(probe_report_path=probe_path)
    assert analysis["bootapp_create_supported"] is True
    assert analysis["device_set_supported"] is True
    assert analysis["path_set_supported"] is True
    assert analysis["recommended_next_strategy"] == "firmware-efi-bootapp-system-dry-run"


def test_cli_demo_bcd_probe_bootapp_elements_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))

    def _fake_probe(*, lab_dir: Path, report_dir: Path) -> BcdBootappElementProbeOutcome:
        report_dir.mkdir(parents=True, exist_ok=True)
        report = BcdBootappElementProbeReport(
            store_path=lab_dir / "bcd_probe" / "bootapp_elements_probe.bcd",
            bootapp_guid="{aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa}",
            create_supported=True,
            element_probes=[],
            enum_output_path=report_dir / "bcd_bootapp_elements_enum_all_v.txt",
            conclusion="bootapp_create_only",
            warnings=[],
            blockers=[],
        )
        report.enum_output_path.write_text("enum", encoding="utf-8")
        stderr_path = report_dir / "bcd_bootapp_elements_enum_all_v.stderr.txt"
        stderr_path.write_text("", encoding="utf-8")
        report_path = report_dir / "bcd_bootapp_elements_probe.json"
        report_path.write_text(json.dumps({"report": report.to_dict()}), encoding="utf-8")
        return BcdBootappElementProbeOutcome(
            report=report,
            report_path=report_path,
            enum_stderr_path=stderr_path,
        )

    monkeypatch.setattr(cli, "probe_bcd_bootapp_elements", _fake_probe)

    code = cli.main(
        [
            "demo",
            "bcd",
            "probe-bootapp-elements",
            "--lab-dir",
            str(tmp_path / "lab"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["conclusion"] == "bootapp_create_only"


def test_cli_demo_bcd_analyze_bootapp_probe_json(tmp_path: Path, capsys) -> None:
    probe_report = tmp_path / "probe.json"
    probe_report.write_text(
        json.dumps(
            {
                "report": {
                    "create_supported": True,
                    "element_probes": [
                        {"element": "device", "value": "partition=C:", "supported": True},
                        {
                            "element": "path",
                            "value": "\\EFI\\LinuxVHDLauncher\\ubuntu-live\\BOOTX64.EFI",
                            "supported": True,
                        },
                    ],
                    "warnings": [],
                    "blockers": [],
                    "conclusion": "bootapp_elements_supported",
                }
            }
        ),
        encoding="utf-8",
    )
    code = cli.main(
        [
            "demo",
            "bcd",
            "analyze-bootapp-probe",
            "--probe-report",
            str(probe_report),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recommended_next_strategy"] == "firmware-efi-bootapp-system-dry-run"


def test_bootapp_vhd_device_probe_uses_store_and_exact_commands(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    lab_dir = tmp_path / "lab"
    report_dir = tmp_path / "reports"
    vhd_path = Path("C:/LVHLab/ubuntu-live.vhdx")

    class FakeRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(self, command: list[str], *, elevated_required: bool = False, check: bool = True) -> CommandResult:
            del elevated_required
            del check
            self.commands.append(command)
            if command[:2] == ["bcdedit", "/createstore"]:
                return CommandResult(tuple(command), 0, "store created", "")
            if "/create" in command and "/application" in command:
                return CommandResult(
                    tuple(command),
                    0,
                    "The entry was successfully created {44444444-4444-4444-4444-444444444444}",
                    "",
                )
            if "/set" in command:
                return CommandResult(tuple(command), 0, "ok", "")
            if "/enum" in command:
                return CommandResult(tuple(command), 0, "enum output", "")
            return CommandResult(tuple(command), 0, "", "")

    fake_runner = FakeRunner()
    monkeypatch.setattr(bcd_probe, "is_windows_platform", lambda: True)
    outcome = probe_bcd_bootapp_vhd_device(
        vhd_path=vhd_path,
        lab_dir=lab_dir,
        report_dir=report_dir,
        runner=fake_runner,  # type: ignore[arg-type]
    )

    expected_store = str(lab_dir / "bcd_probe" / "bootapp_vhd_device_probe.bcd")
    expected_vhd_device = "vhd=[C:]\\LVHLab\\ubuntu-live.vhdx"
    assert outcome.report.conclusion == "bootapp_vhd_device_supported"
    assert all(command[0] == "bcdedit" for command in fake_runner.commands)
    assert all("/copy" not in command for command in fake_runner.commands)
    assert all("{bootmgr}" not in " ".join(command) for command in fake_runner.commands)
    assert [
        "bcdedit",
        "/store",
        expected_store,
        "/set",
        "{44444444-4444-4444-4444-444444444444}",
        "device",
        expected_vhd_device,
    ] in fake_runner.commands
    assert [
        "bcdedit",
        "/store",
        expected_store,
        "/set",
        "{44444444-4444-4444-4444-444444444444}",
        "path",
        "\\EFI\\BOOT\\BOOTX64.EFI",
    ] in fake_runner.commands


def test_analyze_bootapp_vhd_device_probe_recommends_strategy(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = BcdBootappVhdDeviceProbeReport(
        store_path=tmp_path / "lab" / "bcd_probe" / "bootapp_vhd_device_probe.bcd",
        vhd_path=Path("C:/LVHLab/ubuntu-live.vhdx"),
        bootapp_guid="{55555555-5555-5555-5555-555555555555}",
        create_supported=True,
        element_probes=[
            BcdElementSetProbe(
                element="device",
                value="vhd=[C:]\\LVHLab\\ubuntu-live.vhdx",
                supported=True,
                command=["bcdedit", "/store", "x", "/set", "{GUID}", "device", "vhd=[C:]\\LVHLab\\ubuntu-live.vhdx"],
                returncode=0,
                stdout="ok",
                stderr="",
                notes=None,
            ),
            BcdElementSetProbe(
                element="path",
                value="\\EFI\\BOOT\\BOOTX64.EFI",
                supported=True,
                command=["bcdedit", "/store", "x", "/set", "{GUID}", "path", "\\EFI\\BOOT\\BOOTX64.EFI"],
                returncode=0,
                stdout="ok",
                stderr="",
                notes=None,
            ),
        ],
        enum_output_path=report_dir / "bcd_bootapp_vhd_device_enum_all_v.txt",
        conclusion="bootapp_vhd_device_supported",
        warnings=[],
        blockers=[],
    )
    probe_path = report_dir / "bcd_bootapp_vhd_device_probe.json"
    probe_path.write_text(json.dumps({"report": report.to_dict()}), encoding="utf-8")

    analysis = analyze_bcd_bootapp_vhd_device_probe_report(probe_report_path=probe_path)
    assert analysis["bootapp_create_supported"] is True
    assert analysis["vhd_device_set_supported"] is True
    assert analysis["path_set_supported"] is True
    assert analysis["recommended_next_strategy"] == "bootapp-vhd-system-dry-run"


def test_cli_demo_bcd_probe_bootapp_vhd_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))

    def _fake_probe(*, vhd_path: Path, lab_dir: Path, report_dir: Path) -> BcdBootappVhdDeviceProbeOutcome:
        del vhd_path
        report_dir.mkdir(parents=True, exist_ok=True)
        report = BcdBootappVhdDeviceProbeReport(
            store_path=lab_dir / "bcd_probe" / "bootapp_vhd_device_probe.bcd",
            vhd_path=Path("C:/LVHLab/ubuntu-live.vhdx"),
            bootapp_guid="{66666666-6666-6666-6666-666666666666}",
            create_supported=True,
            element_probes=[],
            enum_output_path=report_dir / "bcd_bootapp_vhd_device_enum_all_v.txt",
            conclusion="bootapp_create_only",
            warnings=[],
            blockers=[],
        )
        report.enum_output_path.write_text("enum", encoding="utf-8")
        stderr_path = report_dir / "bcd_bootapp_vhd_device_enum_all_v.stderr.txt"
        stderr_path.write_text("", encoding="utf-8")
        report_path = report_dir / "bcd_bootapp_vhd_device_probe.json"
        report_path.write_text(json.dumps({"report": report.to_dict()}), encoding="utf-8")
        return BcdBootappVhdDeviceProbeOutcome(
            report=report,
            report_path=report_path,
            enum_stderr_path=stderr_path,
        )

    monkeypatch.setattr(cli, "probe_bcd_bootapp_vhd_device", _fake_probe)

    code = cli.main(
        [
            "demo",
            "bcd",
            "probe-bootapp-vhd-device",
            "--vhd",
            "C:\\LVHLab\\ubuntu-live.vhdx",
            "--lab-dir",
            str(tmp_path / "lab"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["report"]["conclusion"] == "bootapp_create_only"


def test_cli_demo_bcd_analyze_bootapp_vhd_probe_json(tmp_path: Path, capsys) -> None:
    probe_report = tmp_path / "probe_vhd.json"
    probe_report.write_text(
        json.dumps(
            {
                "report": {
                    "vhd_path": "C:\\LVHLab\\ubuntu-live.vhdx",
                    "create_supported": True,
                    "element_probes": [
                        {
                            "element": "device",
                            "value": "vhd=[C:]\\LVHLab\\ubuntu-live.vhdx",
                            "supported": True,
                        },
                        {
                            "element": "path",
                            "value": "\\EFI\\BOOT\\BOOTX64.EFI",
                            "supported": True,
                        },
                    ],
                    "warnings": [],
                    "blockers": [],
                    "conclusion": "bootapp_vhd_device_supported",
                }
            }
        ),
        encoding="utf-8",
    )
    code = cli.main(
        [
            "demo",
            "bcd",
            "analyze-bootapp-vhd-device-probe",
            "--probe-report",
            str(probe_report),
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recommended_next_strategy"] == "bootapp-vhd-system-dry-run"
