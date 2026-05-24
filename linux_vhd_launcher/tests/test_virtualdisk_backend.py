from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher.errors import UnsupportedPlatformError
from linux_vhd_launcher.models import VhdSpec
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate
from linux_vhd_launcher.system.windows_vhd import FakeVirtDiskApi, VirtualDiskApiBackend


def _gate(tmp_path: Path, *, is_windows: bool) -> RealWindowsOpsGate:
    lab_dir = tmp_path / "lab"
    return RealWindowsOpsGate(
        execute_real_windows_ops=True,
        confirmation_token=True,
        dry_run=False,
        backup_path=lab_dir / "backup.bcd",
        allowed_lab_dir=lab_dir,
        validation_report_path=lab_dir / "report.json",
        platform_checker=lambda: is_windows,
        admin_checker=lambda: True,
    )


def test_virtualdisk_backend_flow_uses_api_and_closes_handles(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir(parents=True)
    fake_api = FakeVirtDiskApi()
    backend = VirtualDiskApiBackend(gate=_gate(tmp_path, is_windows=True), api=fake_api)

    spec = VhdSpec(path=lab_dir / "disk.vhdx", size_gb=1, format="vhdx")
    backend.create_vhd(spec)
    backend.attach_vhd(spec.path)
    backend.detach_vhd(spec.path)

    assert spec.path in fake_api.created_paths
    assert spec.path in fake_api.opened_paths
    assert fake_api.attached_handles
    assert fake_api.detached_handles
    assert len(fake_api.closed_handles) >= 3


def test_virtualdisk_backend_refuses_non_windows(tmp_path: Path) -> None:
    lab_dir = tmp_path / "lab"
    lab_dir.mkdir(parents=True)
    fake_api = FakeVirtDiskApi()
    backend = VirtualDiskApiBackend(gate=_gate(tmp_path, is_windows=False), api=fake_api)

    with pytest.raises(UnsupportedPlatformError):
        backend.create_vhd(VhdSpec(path=lab_dir / "disk.vhdx", size_gb=1, format="vhdx"))
