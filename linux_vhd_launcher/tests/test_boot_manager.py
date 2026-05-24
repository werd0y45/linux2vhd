from __future__ import annotations

from pathlib import Path

from linux_vhd_launcher.config import RegistryStore
from linux_vhd_launcher.services.boot_manager import BootManager, RegistryUpdater
from linux_vhd_launcher.system.windows_bcd import BcdCommandBuilder, FakeBcdBackend


def test_boot_manager_create_and_delete(tmp_path: Path) -> None:
    manager = BootManager(
        backend=FakeBcdBackend(),
        command_builder=BcdCommandBuilder(),
        registry_updater=RegistryUpdater(RegistryStore(tmp_path / "registry.json")),
    )

    entry = manager.create_entry(
        description="Linux",
        device="vhd=[C:]\\linux.vhdx",
        loader_path=r"\EFI\BOOT\BOOTX64.EFI",
    )
    assert entry.guid.startswith("{")

    manager.delete_entry(entry.guid)


def test_boot_manager_plan_contains_dangerous_steps(tmp_path: Path) -> None:
    manager = BootManager(
        backend=FakeBcdBackend(),
        command_builder=BcdCommandBuilder(),
        registry_updater=RegistryUpdater(RegistryStore(tmp_path / "registry.json")),
    )

    plan = manager.build_plan(
        description="Linux",
        device="vhd=[C:]\\linux.vhdx",
        loader_path=r"\EFI\BOOT\BOOTX64.EFI",
    )

    assert plan[0].startswith("EXPERIMENTAL:")
    assert any(step.startswith("DANGEROUS:") for step in plan)
