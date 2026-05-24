from __future__ import annotations

from pathlib import Path

from linux_vhd_launcher.system.windows_bcd import BcdCommandBuilder


def test_bcd_command_builder_copy_current() -> None:
    builder = BcdCommandBuilder()
    cmd = builder.copy_current_entry("DebugEntry")
    assert cmd == ("bcdedit", "/copy", "{current}", "/d", "DebugEntry")


def test_bcd_command_builder_sets() -> None:
    builder = BcdCommandBuilder()
    guid = "{11111111-1111-1111-1111-111111111111}"

    assert builder.set_device(guid, "vhd=[C:]\\linux.vhdx") == (
        "bcdedit",
        "/set",
        guid,
        "device",
        "vhd=[C:]\\linux.vhdx",
    )
    assert builder.set_path(guid, r"\EFI\BOOT\BOOTX64.EFI") == (
        "bcdedit",
        "/set",
        guid,
        "path",
        r"\EFI\BOOT\BOOTX64.EFI",
    )


def test_bcd_command_builder_backup_and_delete(tmp_path: Path) -> None:
    builder = BcdCommandBuilder()
    guid = "{11111111-1111-1111-1111-111111111111}"

    assert builder.export_backup(tmp_path / "backup.bcd")[:2] == ("bcdedit", "/export")
    assert builder.delete_entry(guid) == ("bcdedit", "/delete", guid, "/f")
