from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher.config import RegistryStore
from linux_vhd_launcher.errors import RollbackError
from linux_vhd_launcher.models import RegistryItem, VhdSpec
from linux_vhd_launcher.services.boot_manager import BootManager, RegistryUpdater
from linux_vhd_launcher.services.installer_service import (
    FakeDeploymentBackend,
    InstallerService,
    InstallRequest,
)
from linux_vhd_launcher.services.iso_manager import ISOManager
from linux_vhd_launcher.services.secure_boot_helper import SecureBootHelper
from linux_vhd_launcher.services.vhd_manager import VHDManager
from linux_vhd_launcher.system.windows_bcd import BcdCommandBuilder, FakeBcdBackend
from linux_vhd_launcher.system.windows_vhd import FakeVhdBackend


class FailingRegistryStore(RegistryStore):
    def add_item(self, item: RegistryItem) -> None:
        raise RuntimeError("registry write failed")


class FailingDetachVhdBackend(FakeVhdBackend):
    def detach_vhd(self, path: Path) -> None:
        raise RuntimeError("detach failed")


def _make_service(
    tmp_path: Path,
    *,
    fail_deploy: bool = False,
    failing_registry: bool = False,
    failing_detach: bool = False,
) -> tuple[InstallerService, FakeVhdBackend, FakeBcdBackend]:
    iso_manager = ISOManager(tmp_path / "catalog.json")
    vhd_backend: FakeVhdBackend
    if failing_detach:
        vhd_backend = FailingDetachVhdBackend(free_space_bytes=200 * 1024**3)
    else:
        vhd_backend = FakeVhdBackend(free_space_bytes=200 * 1024**3)

    vhd_manager = VHDManager(vhd_backend)
    bcd_backend = FakeBcdBackend()

    registry_store: RegistryStore
    if failing_registry:
        registry_store = FailingRegistryStore(tmp_path / "registry.json")
    else:
        registry_store = RegistryStore(tmp_path / "registry.json")

    boot_manager = BootManager(
        backend=bcd_backend,
        command_builder=BcdCommandBuilder(),
        registry_updater=RegistryUpdater(registry_store),
    )

    service = InstallerService(
        iso_manager=iso_manager,
        vhd_manager=vhd_manager,
        boot_manager=boot_manager,
        secure_boot_helper=SecureBootHelper(),
        deployment_backend=FakeDeploymentBackend(fail=fail_deploy),
    )
    return service, vhd_backend, bcd_backend


def _request(tmp_path: Path) -> InstallRequest:
    iso_path = tmp_path / "linux.iso"
    iso_path.write_bytes(b"iso")
    return InstallRequest(
        iso_path=iso_path,
        vhd_spec=VhdSpec(path=tmp_path / "linux.vhdx", size_gb=20, format="vhdx"),
        description="Linux",
        dry_run=True,
    )


def test_installer_happy_path(tmp_path: Path) -> None:
    service, _, _ = _make_service(tmp_path)
    result = service.install(_request(tmp_path))
    assert result.success is True
    assert result.bcd_guid is not None


def test_installer_rollback_after_attach_runs_detach_and_cleanup(tmp_path: Path) -> None:
    service, vhd_backend, _ = _make_service(tmp_path, fail_deploy=True)

    with pytest.raises(RuntimeError):
        service.install(_request(tmp_path))

    assert (tmp_path / "linux.vhdx") in vhd_backend.detached


def test_installer_rollback_after_bcd_create_deletes_bcd_entry(tmp_path: Path) -> None:
    service, _, bcd_backend = _make_service(tmp_path, failing_registry=True)

    with pytest.raises(RuntimeError):
        service.install(_request(tmp_path))

    assert bcd_backend.entries == {}


def test_installer_rollback_error_keeps_original_exception(tmp_path: Path) -> None:
    service, _, _ = _make_service(tmp_path, fail_deploy=True, failing_detach=True)

    with pytest.raises(RollbackError) as exc_info:
        service.install(_request(tmp_path))

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "Deployment backend failed" in str(exc_info.value.__cause__)
