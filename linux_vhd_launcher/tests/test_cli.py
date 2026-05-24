from __future__ import annotations

import json
from pathlib import Path

from linux_vhd_launcher import cli


def test_cli_plan_install_dry_run(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))

    iso_path = tmp_path / "linux.iso"
    iso_path.write_bytes(b"iso")
    vhd_path = tmp_path / "linux.vhdx"

    code = cli.main(
        [
            "plan-install",
            "--iso",
            str(iso_path),
            "--vhd",
            str(vhd_path),
            "--size-gb",
            "20",
            "--format",
            "vhdx",
            "--dry-run",
        ]
    )

    assert code == 0


def test_cli_plan_install_json_uses_operation_plan(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    iso_path = tmp_path / "linux.iso"
    iso_path.write_bytes(b"iso")

    code = cli.main(
        [
            "plan-install",
            "--iso",
            str(iso_path),
            "--vhd",
            str(tmp_path / "linux.vhdx"),
            "--size-gb",
            "20",
            "--format",
            "vhdx",
            "--dry-run",
            "--output-format",
            "json",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["title"] == "Full Install Plan"
    assert isinstance(payload["steps"], list)
    assert isinstance(payload["warnings"], list)
    assert payload["dangerous"] is True
    assert payload["experimental"] is True


def test_cli_doctor(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    assert cli.main(["doctor"]) == 0


def test_cli_doctor_json(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    assert cli.main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "os" in payload
    assert "is_admin" in payload
    assert "dry_run_available" in payload


def test_cli_show_registry_empty(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    assert cli.main(["show-registry"]) == 0


def test_cli_install_non_windows_requires_dry_run(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))

    iso_path = tmp_path / "linux.iso"
    iso_path.write_bytes(b"iso")
    vhd_path = tmp_path / "linux.vhdx"

    code = cli.main(
        [
            "install",
            "--iso",
            str(iso_path),
            "--vhd",
            str(vhd_path),
            "--size-gb",
            "20",
            "--format",
            "vhdx",
        ]
    )
    assert code == 2


def test_cli_scan_iso(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    isod = tmp_path / "isos"
    isod.mkdir()
    (isod / "x.iso").write_bytes(b"x")

    assert cli.main(["scan-iso", str(isod)]) == 0


def test_cli_plan_windows_lab(tmp_path: Path, monkeypatch, capsys) -> None:  # noqa: ANN001
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    assert cli.main(["plan-windows-lab", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["title"] == "Windows VM Lab Validation Plan"
    assert isinstance(payload["warnings"], list)
    assert payload["dangerous"] is True
    assert payload["experimental"] is True
