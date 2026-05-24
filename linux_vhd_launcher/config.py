"""Configuration and local registry persistence."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from linux_vhd_launcher.errors import (
    DuplicateRegistryGuidError,
    RegistryFormatError,
)
from linux_vhd_launcher.models import AppConfig, RegistryItem

REGISTRY_VERSION = 1


class ConfigManager:
    """Loads or initializes application configuration from JSON."""

    def __init__(self, config_path: Path, default_config_path: Path | None = None) -> None:
        self._config_path = config_path
        self._default_config_path = default_config_path

    def load_or_create(self) -> AppConfig:
        """Load config from disk, creating it from defaults if missing."""
        if not self._config_path.exists():
            config = self._load_default_config()
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write_json(self._config_path, self._serialize_config(config))
            return config

        raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        return self._deserialize_config(raw)

    def _load_default_config(self) -> AppConfig:
        if self._default_config_path and self._default_config_path.exists():
            raw = json.loads(self._default_config_path.read_text(encoding="utf-8"))
            return self._deserialize_config(raw)

        root = Path.cwd()
        return AppConfig(
            default_vhd_dir=root / "vhd",
            default_vhd_size_gb=40,
            bcd_backup_dir=root / "backups",
            log_level="INFO",
            catalog_path=root / "catalog.json",
            registry_path=root / "vhd_registry.json",
        )

    def _deserialize_config(self, raw: dict[str, Any]) -> AppConfig:
        return AppConfig(
            default_vhd_dir=Path(raw["default_vhd_dir"]),
            default_vhd_size_gb=int(raw["default_vhd_size_gb"]),
            bcd_backup_dir=Path(raw["bcd_backup_dir"]),
            log_level=str(raw["log_level"]),
            catalog_path=Path(raw["catalog_path"]),
            registry_path=Path(raw["registry_path"]),
        )

    def _serialize_config(self, config: AppConfig) -> dict[str, Any]:
        raw = asdict(config)
        return {
            "default_vhd_dir": str(raw["default_vhd_dir"]),
            "default_vhd_size_gb": raw["default_vhd_size_gb"],
            "bcd_backup_dir": str(raw["bcd_backup_dir"]),
            "log_level": raw["log_level"],
            "catalog_path": str(raw["catalog_path"]),
            "registry_path": str(raw["registry_path"]),
        }

    def _atomic_write_json(self, path: Path, payload: dict[str, Any]) -> None:
        _atomic_write_json(path, payload)


class RegistryStore:
    """JSON-backed local registry for installed VHD entries."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def list_items(self) -> list[RegistryItem]:
        """Return all registry entries."""
        if not self._path.exists():
            return []

        text = self._path.read_text(encoding="utf-8").strip()
        if text == "":
            return []

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RegistryFormatError(f"Registry JSON is corrupted: {self._path}") from exc

        if isinstance(raw, list):
            # Legacy v0 format support.
            rows: list[dict[str, Any]] = raw
        elif isinstance(raw, dict):
            version = raw.get("version")
            if version != REGISTRY_VERSION:
                raise RegistryFormatError(
                    f"Unsupported registry version {version!r}, expected {REGISTRY_VERSION}."
                )
            rows_any = raw.get("items")
            if not isinstance(rows_any, list):
                raise RegistryFormatError("Registry 'items' must be a list.")
            rows = rows_any
        else:
            raise RegistryFormatError("Registry root must be either list or object.")

        return [self._deserialize_item(item) for item in rows]

    def add_item(self, item: RegistryItem) -> None:
        """Append a new registry entry."""
        items = self.list_items()
        if any(existing.bcd_guid == item.bcd_guid for existing in items):
            raise DuplicateRegistryGuidError(f"Registry already contains GUID: {item.bcd_guid}")
        items.append(item)
        self._write_items(items)

    def remove_by_guid(self, guid: str) -> bool:
        """Remove entry by BCD GUID."""
        items = self.list_items()
        filtered = [item for item in items if item.bcd_guid != guid]
        if len(filtered) == len(items):
            return False
        self._write_items(filtered)
        return True

    def _write_items(self, items: list[RegistryItem]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": REGISTRY_VERSION,
            "items": [self._serialize_item(item) for item in items],
        }
        _atomic_write_json(self._path, payload)

    def _serialize_item(self, item: RegistryItem) -> dict[str, Any]:
        return {
            "distro": item.distro,
            "vhd_path": str(item.vhd_path),
            "bcd_guid": item.bcd_guid,
            "created_at": item.created_at.isoformat(),
            "bcd_backup_path": str(item.bcd_backup_path) if item.bcd_backup_path else None,
        }

    def _deserialize_item(self, raw: dict[str, Any]) -> RegistryItem:
        return RegistryItem(
            distro=str(raw["distro"]),
            vhd_path=Path(raw["vhd_path"]),
            bcd_guid=str(raw["bcd_guid"]),
            created_at=datetime.fromisoformat(raw["created_at"]),
            bcd_backup_path=Path(raw["bcd_backup_path"]) if raw["bcd_backup_path"] else None,
        )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write JSON to disk with best-effort fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        tmp_path.replace(path)

        # Best-effort directory fsync to improve durability guarantees.
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
