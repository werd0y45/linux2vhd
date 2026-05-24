from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher import cli
from linux_vhd_launcher.models import BcdEntry
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate
from linux_vhd_launcher.validation import StepExecutionError


class FakeBcdBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | Path]] = []
        self.guid = "{11111111-1111-1111-1111-111111111111}"

    def export_backup(self, path: Path) -> Path:
        self.calls.append(("export", path))
        return path

    def create_entry(self, description: str) -> BcdEntry:
        self.calls.append(("create", description))
        return BcdEntry(guid=self.guid, description=description, loader_path=None)

    def set_entry_device(self, guid: str, device: str) -> None:
        self.calls.append(("set-device", guid))

    def set_entry_path(self, guid: str, loader_path: str) -> None:
        self.calls.append(("set-path", guid))

    def add_to_display_order(self, guid: str) -> None:
        self.calls.append(("displayorder", guid))

    def delete_entry(self, guid: str) -> None:
        self.calls.append(("delete", guid))


class FakeRunner:
    def __init__(self, *, dry_run: bool, stdout: str) -> None:
        self.stdout = stdout
        self.commands: list[list[str]] = []

    def run(self, command, *, elevated_required: bool, check: bool):  # noqa: ANN001
        del elevated_required, check
        self.commands.append(list(command))
        return type(
            "Result",
            (),
            {"returncode": 0, "stdout": self.stdout, "stderr": ""},
        )()


def _gate(tmp_path: Path) -> RealWindowsOpsGate:
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir(parents=True, exist_ok=True)
    return RealWindowsOpsGate(
        execute_real_windows_ops=True,
        confirmation_token=True,
        dry_run=False,
        backup_path=lab_dir / "backup.bcd",
        allowed_lab_dir=lab_dir,
        validation_report_path=lab_dir / "report.json",
        platform_checker=lambda: True,
        admin_checker=lambda: True,
    )


def test_linux_refuses_mutation_command(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    report_dir = tmp_path / "report"
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
            "--no-dry-run",
            "--confirm-vm-snapshot",
        ]
    )
    assert code == 2


def test_mocked_windows_without_snapshot_refuses(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    report_dir = tmp_path / "report"
    assert cli.main(["validation", "init", "--report-dir", str(report_dir)]) == 0

    monkeypatch.setattr(cli, "is_windows_platform", lambda: True)
    monkeypatch.setattr(cli, "is_admin", lambda: True)

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
            "--no-dry-run",
        ]
    )
    assert code == 2


def test_mutation_flow_with_all_flags_uses_expected_commands(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    backend = FakeBcdBackend()
    runner = FakeRunner(dry_run=False, stdout="")

    monkeypatch.setattr(cli, "is_windows_platform", lambda: True)
    monkeypatch.setattr(cli, "is_admin", lambda: True)
    monkeypatch.setattr(cli, "create_windows_bcd_backend", lambda _runner, gate: backend)
    monkeypatch.setattr(cli, "CommandRunner", lambda dry_run: runner)

    result = cli._run_windows_bcd_mutation_smoke(
        report_dir=tmp_path,
        lab_dir=_gate(tmp_path).allowed_lab_dir or tmp_path,
        include_displayorder_experiment=False,
        gate=_gate(tmp_path),
    )

    assert result.rollback_evidence is not None
    assert result.rollback_evidence.status == "pass"
    call_names = [name for name, _ in backend.calls]
    assert call_names[:3] == ["export", "create", "delete"]
    assert "displayorder" not in call_names
    assert runner.commands and runner.commands[0][:3] == ["bcdedit", "/enum", "all"]


def test_mutation_rollback_called_if_verify_fails(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    backend = FakeBcdBackend()
    runner = FakeRunner(dry_run=False, stdout=backend.guid)

    monkeypatch.setattr(cli, "is_windows_platform", lambda: True)
    monkeypatch.setattr(cli, "is_admin", lambda: True)
    monkeypatch.setattr(cli, "create_windows_bcd_backend", lambda _runner, gate: backend)
    monkeypatch.setattr(cli, "CommandRunner", lambda dry_run: runner)

    with pytest.raises(StepExecutionError):
        cli._run_windows_bcd_mutation_smoke(
            report_dir=tmp_path,
            lab_dir=_gate(tmp_path).allowed_lab_dir or tmp_path,
            include_displayorder_experiment=False,
            gate=_gate(tmp_path),
        )

    delete_calls = [name for name, _ in backend.calls if name == "delete"]
    assert len(delete_calls) == 2
