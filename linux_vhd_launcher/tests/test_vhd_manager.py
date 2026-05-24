from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher.errors import InsufficientSpaceError
from linux_vhd_launcher.models import VhdSpec
from linux_vhd_launcher.services.vhd_manager import VHDManager
from linux_vhd_launcher.system.windows_vhd import FakeVhdBackend


def test_vhd_manager_insufficient_space(tmp_path: Path) -> None:
    backend = FakeVhdBackend(free_space_bytes=1)
    manager = VHDManager(backend)

    with pytest.raises(InsufficientSpaceError):
        manager.check_free_space(tmp_path / "disk.vhdx", required_gb=1)


def test_vhd_manager_create_and_attach(tmp_path: Path) -> None:
    backend = FakeVhdBackend(free_space_bytes=10_000 * 1024**3)
    manager = VHDManager(backend)
    target = tmp_path / "disk.vhdx"

    manager.create(
        VhdSpec(
            path=target,
            size_gb=20,
            format="vhdx",
        )
    )
    manager.attach(target)

    assert target in backend.created
    assert target in backend.attached
