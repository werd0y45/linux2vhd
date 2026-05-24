"""Boot entry orchestration service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from linux_vhd_launcher.config import RegistryStore
from linux_vhd_launcher.errors import BcdOperationError
from linux_vhd_launcher.models import BcdEntry, RegistryItem
from linux_vhd_launcher.system.windows_bcd import BcdBackend, BcdCommandBuilder


@dataclass(slots=True)
class RegistryUpdater:
    """Coordinates registry persistence independently from BCD execution."""

    registry: RegistryStore

    def save(
        self,
        *,
        distro: str,
        vhd_path: Path,
        bcd_guid: str,
        bcd_backup_path: Path | None,
    ) -> RegistryItem:
        item = RegistryItem(
            distro=distro,
            vhd_path=vhd_path,
            bcd_guid=bcd_guid,
            created_at=datetime.now(UTC),
            bcd_backup_path=bcd_backup_path,
        )
        self.registry.add_item(item)
        return item

    def remove(self, guid: str) -> bool:
        return self.registry.remove_by_guid(guid)


@dataclass(slots=True)
class BootManager:
    """Service for safe BCD updates and local registry writes."""

    backend: BcdBackend
    command_builder: BcdCommandBuilder
    registry_updater: RegistryUpdater

    def build_plan(self, *, description: str, device: str, loader_path: str) -> list[str]:
        """Return human-readable BCD command plan for dry-run and diagnostics."""
        placeholder_guid = "{new-guid}"
        commands = [
            self.command_builder.copy_current_entry(description),
            self.command_builder.set_device(placeholder_guid, device),
            self.command_builder.set_path(placeholder_guid, loader_path),
            self.command_builder.add_to_display_order(placeholder_guid),
        ]
        return [
            "EXPERIMENTAL: " + " ".join(commands[0]),
            "DANGEROUS: " + " ".join(commands[1]),
            "DANGEROUS: " + " ".join(commands[2]),
            "DANGEROUS: " + " ".join(commands[3]),
            f"description={description}",
            f"device={device}",
            f"loader_path={loader_path}",
        ]

    def export_backup(self, backup_path: Path) -> Path:
        """Export and return BCD backup file path."""
        try:
            return self.backend.export_backup(backup_path)
        except Exception as exc:
            raise BcdOperationError(f"Failed to export BCD backup: {exc}") from exc

    def create_entry(
        self,
        *,
        description: str,
        device: str,
        loader_path: str,
    ) -> BcdEntry:
        """Create and configure a BCD entry."""
        try:
            entry = self.backend.create_entry(description)
            self.backend.set_entry_device(entry.guid, device)
            self.backend.set_entry_path(entry.guid, loader_path)
            self.backend.add_to_display_order(entry.guid)
            return BcdEntry(guid=entry.guid, description=description, loader_path=loader_path)
        except Exception as exc:
            raise BcdOperationError(f"Failed to create BCD entry: {exc}") from exc

    def delete_entry(self, guid: str) -> None:
        """Delete an existing BCD entry."""
        try:
            self.backend.delete_entry(guid)
        except Exception as exc:
            raise BcdOperationError(f"Failed to delete BCD entry: {exc}") from exc

    def save_registry_item(
        self,
        *,
        distro: str,
        vhd_path: Path,
        bcd_guid: str,
        bcd_backup_path: Path | None,
    ) -> RegistryItem:
        """Store installation metadata in local registry."""
        return self.registry_updater.save(
            distro=distro,
            vhd_path=vhd_path,
            bcd_guid=bcd_guid,
            bcd_backup_path=bcd_backup_path,
        )

    def remove_registry_item(self, guid: str) -> bool:
        """Remove registry entry by GUID."""
        return self.registry_updater.remove(guid)
