from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher.errors import UnsafeRealOperationError, UnsupportedPlatformError
from linux_vhd_launcher.models import VhdSpec
from linux_vhd_launcher.system.runner import CommandRunner
from linux_vhd_launcher.system.windows_bcd import create_windows_bcd_backend
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate
from linux_vhd_launcher.system.windows_vhd import DiskPartVhdBackend, VirtualDiskApiBackend


def _gate(
    *,
    is_windows: bool,
    is_admin: bool,
    execute: bool,
    dry_run: bool,
    token: bool,
    backup: Path | None,
) -> RealWindowsOpsGate:
    return RealWindowsOpsGate(
        execute_real_windows_ops=execute,
        confirmation_token=token,
        dry_run=dry_run,
        backup_path=backup,
        platform_checker=lambda: is_windows,
        admin_checker=lambda: is_admin,
    )


def test_linux_always_refuses_real_windows_bcd_ops(tmp_path: Path) -> None:
    backend = create_windows_bcd_backend(
        CommandRunner(dry_run=False),
        gate=_gate(
            is_windows=False,
            is_admin=True,
            execute=True,
            dry_run=False,
            token=True,
            backup=tmp_path / "backup.bcd",
        ),
    )
    with pytest.raises(UnsafeRealOperationError):
        backend.export_backup(tmp_path / "backup.bcd")


def test_windows_without_admin_refuses(tmp_path: Path) -> None:
    backend = create_windows_bcd_backend(
        CommandRunner(dry_run=False),
        gate=_gate(
            is_windows=True,
            is_admin=False,
            execute=True,
            dry_run=False,
            token=True,
            backup=tmp_path / "backup.bcd",
        ),
    )
    with pytest.raises(UnsafeRealOperationError):
        backend.export_backup(tmp_path / "backup.bcd")


def test_admin_without_explicit_flag_refuses(tmp_path: Path) -> None:
    backend = create_windows_bcd_backend(
        CommandRunner(dry_run=False),
        gate=_gate(
            is_windows=True,
            is_admin=True,
            execute=False,
            dry_run=False,
            token=True,
            backup=tmp_path / "backup.bcd",
        ),
    )
    with pytest.raises(UnsafeRealOperationError):
        backend.export_backup(tmp_path / "backup.bcd")


def test_confirmation_token_is_required(tmp_path: Path) -> None:
    backend = create_windows_bcd_backend(
        CommandRunner(dry_run=False),
        gate=_gate(
            is_windows=True,
            is_admin=True,
            execute=True,
            dry_run=False,
            token=False,
            backup=tmp_path / "backup.bcd",
        ),
    )
    with pytest.raises(UnsafeRealOperationError):
        backend.export_backup(tmp_path / "backup.bcd")


def test_backup_path_is_required(tmp_path: Path) -> None:
    backend = create_windows_bcd_backend(
        CommandRunner(dry_run=False),
        gate=_gate(
            is_windows=True,
            is_admin=True,
            execute=True,
            dry_run=False,
            token=True,
            backup=None,
        ),
    )
    with pytest.raises(UnsafeRealOperationError):
        backend.export_backup(tmp_path / "backup.bcd")


def test_explicit_flag_but_dry_run_refuses_real_backend(tmp_path: Path) -> None:
    backend = create_windows_bcd_backend(
        CommandRunner(dry_run=False),
        gate=_gate(
            is_windows=True,
            is_admin=True,
            execute=True,
            dry_run=True,
            token=True,
            backup=tmp_path / "backup.bcd",
        ),
    )
    with pytest.raises(UnsafeRealOperationError):
        backend.export_backup(tmp_path / "backup.bcd")


def test_windows_vhd_backend_refuses_without_gate(tmp_path: Path) -> None:
    backend = DiskPartVhdBackend(
        CommandRunner(dry_run=False),
        gate=_gate(
            is_windows=True,
            is_admin=True,
            execute=False,
            dry_run=False,
            token=True,
            backup=tmp_path / "backup.bcd",
        ),
    )
    with pytest.raises(UnsafeRealOperationError):
        backend.create_vhd(VhdSpec(path=tmp_path / "x.vhdx", size_gb=20, format="vhdx"))


def test_virtdisk_backend_refuses_on_linux(tmp_path: Path) -> None:
    backend = VirtualDiskApiBackend(
        gate=_gate(
            is_windows=False,
            is_admin=False,
            execute=True,
            dry_run=False,
            token=True,
            backup=tmp_path / "backup.bcd",
        )
    )
    with pytest.raises((UnsafeRealOperationError, UnsupportedPlatformError)):
        backend.create_virtual_disk(VhdSpec(path=tmp_path / "disk.vhdx", size_gb=5, format="vhdx"))
