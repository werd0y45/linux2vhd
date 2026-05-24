from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from linux_vhd_launcher.config import ConfigManager, RegistryStore
from linux_vhd_launcher.errors import DuplicateRegistryGuidError, RegistryFormatError
from linux_vhd_launcher.models import RegistryItem


def _item(tmp_path: Path, guid: str = "{123}") -> RegistryItem:
    return RegistryItem(
        distro="Ubuntu",
        vhd_path=tmp_path / "ubuntu.vhdx",
        bcd_guid=guid,
        created_at=datetime.now(UTC),
        bcd_backup_path=tmp_path / "backup.bcd",
    )


def test_config_manager_creates_config(tmp_path: Path) -> None:
    default = tmp_path / "default.json"
    default.write_text(
        json.dumps(
            {
                "default_vhd_dir": "./vhd",
                "default_vhd_size_gb": 40,
                "bcd_backup_dir": "./backups",
                "log_level": "INFO",
                "catalog_path": "./catalog.json",
                "registry_path": "./registry.json",
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.json"

    manager = ConfigManager(config_path, default)
    config = manager.load_or_create()

    assert config_path.exists()
    assert config.default_vhd_size_gb == 40


def test_registry_store_add_and_remove(tmp_path: Path) -> None:
    store = RegistryStore(tmp_path / "registry.json")
    store.add_item(_item(tmp_path, "{123}"))

    rows = store.list_items()
    assert len(rows) == 1
    assert rows[0].bcd_guid == "{123}"

    removed = store.remove_by_guid("{123}")
    assert removed is True
    assert store.list_items() == []


def test_registry_store_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text("", encoding="utf-8")
    store = RegistryStore(path)
    assert store.list_items() == []


def test_registry_store_corrupted_json(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text("{broken", encoding="utf-8")
    store = RegistryStore(path)

    with pytest.raises(RegistryFormatError):
        store.list_items()


def test_registry_store_duplicate_guid(tmp_path: Path) -> None:
    store = RegistryStore(tmp_path / "registry.json")
    store.add_item(_item(tmp_path, "{dup}"))

    with pytest.raises(DuplicateRegistryGuidError):
        store.add_item(_item(tmp_path, "{dup}"))


def test_registry_store_legacy_format_support(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    payload = [
        {
            "distro": "Ubuntu",
            "vhd_path": str(tmp_path / "ubuntu.vhdx"),
            "bcd_guid": "{legacy}",
            "created_at": datetime.now(UTC).isoformat(),
            "bcd_backup_path": None,
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    store = RegistryStore(path)
    rows = store.list_items()
    assert rows[0].bcd_guid == "{legacy}"


def test_registry_store_versioned_structure_written(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    store = RegistryStore(path)
    store.add_item(_item(tmp_path, "{v1}"))

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert isinstance(raw["items"], list)
