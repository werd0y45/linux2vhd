from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher.errors import UnsafeRealOperationError
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate


def _gate(
    *,
    is_windows: bool,
    is_admin: bool,
    execute: bool,
    dry_run: bool,
    token: bool,
    backup: Path | None,
    allowed_lab_dir: Path | None,
    report_path: Path | None,
) -> RealWindowsOpsGate:
    return RealWindowsOpsGate(
        execute_real_windows_ops=execute,
        confirmation_token=token,
        dry_run=dry_run,
        backup_path=backup,
        allowed_lab_dir=allowed_lab_dir,
        validation_report_path=report_path,
        platform_checker=lambda: is_windows,
        admin_checker=lambda: is_admin,
    )


def test_refuses_target_path_outside_allowed_lab(tmp_path: Path) -> None:
    gate = _gate(
        is_windows=True,
        is_admin=True,
        execute=True,
        dry_run=False,
        token=True,
        backup=tmp_path / "bcd.bak",
        allowed_lab_dir=tmp_path / "lab",
        report_path=tmp_path / "lab" / "report.json",
    )

    with pytest.raises(UnsafeRealOperationError):
        gate.assert_allowed(
            operation="test",
            rollback_plan="cleanup",
            target_path=tmp_path / "outside" / "disk.vhdx",
            require_rollback_plan=True,
            require_report=True,
            require_target_in_lab_dir=True,
        )


def test_refuses_missing_rollback_plan(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    gate = _gate(
        is_windows=True,
        is_admin=True,
        execute=True,
        dry_run=False,
        token=True,
        backup=lab / "bcd.bak",
        allowed_lab_dir=lab,
        report_path=lab / "report.json",
    )

    with pytest.raises(UnsafeRealOperationError):
        gate.assert_allowed(
            operation="test",
            rollback_plan=None,
            target_path=lab / "x.vhdx",
            require_rollback_plan=True,
            require_report=True,
            require_target_in_lab_dir=True,
        )


def test_all_conditions_true_allows(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    gate = _gate(
        is_windows=True,
        is_admin=True,
        execute=True,
        dry_run=False,
        token=True,
        backup=lab / "bcd.bak",
        allowed_lab_dir=lab,
        report_path=lab / "report.json",
    )

    gate.assert_allowed(
        operation="test",
        rollback_plan="cleanup",
        target_path=lab / "x.vhdx",
        require_rollback_plan=True,
        require_report=True,
        require_target_in_lab_dir=True,
    )
