"""Windows BCD command builder and backend implementations."""

from __future__ import annotations

import re
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from linux_vhd_launcher.errors import (
    BcdOperationError,
    ExperimentalBootChainWarning,
    UnsupportedBootChainError,
)
from linux_vhd_launcher.models import BcdEntry
from linux_vhd_launcher.system.runner import CommandResult, CommandRunner
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate

_GUID_RE = re.compile(r"\{[0-9a-fA-F\-]+\}")


class BcdBackend(Protocol):
    """Protocol for boot configuration operations."""

    def export_backup(self, path: Path) -> Path:
        """Export current BCD store to the given path."""
        ...

    def create_entry(self, description: str) -> BcdEntry:
        """Create and return a new boot entry."""
        ...

    def set_entry_device(self, guid: str, device: str) -> None:
        """Set boot entry device element."""
        ...

    def set_entry_path(self, guid: str, loader_path: str) -> None:
        """Set boot entry path element."""
        ...

    def add_to_display_order(self, guid: str) -> None:
        """Append entry to Boot Manager display order."""
        ...

    def delete_entry(self, guid: str) -> None:
        """Delete boot entry by GUID."""
        ...


@dataclass(slots=True)
class BcdCommandBuilder:
    """Builds BCDEdit commands using documented stable forms."""

    def export_backup(self, path: Path) -> tuple[str, ...]:
        return ("bcdedit", "/export", str(path))

    def copy_current_entry(self, description: str) -> tuple[str, ...]:
        # Based on Microsoft "Add Boot Entries" examples:
        # bcdedit /copy {current} /d "DebugEntry"
        return ("bcdedit", "/copy", "{current}", "/d", description)

    def set_device(self, guid: str, device: str) -> tuple[str, ...]:
        return ("bcdedit", "/set", guid, "device", device)

    def set_path(self, guid: str, loader_path: str) -> tuple[str, ...]:
        return ("bcdedit", "/set", guid, "path", loader_path)

    def add_to_display_order(self, guid: str) -> tuple[str, ...]:
        return ("bcdedit", "/displayorder", guid, "/addlast")

    def delete_entry(self, guid: str) -> tuple[str, ...]:
        return ("bcdedit", "/delete", guid, "/f")


@dataclass(slots=True)
class RunnerBcdExecutor:
    """Executes BCD commands via CommandRunner."""

    runner: CommandRunner
    gate: RealWindowsOpsGate | None

    def execute(
        self,
        command: Sequence[str],
        *,
        elevated_required: bool = True,
        check: bool = True,
    ) -> CommandResult:
        if self.gate is not None:
            self.gate.assert_allowed(
                operation="bcdedit",
                rollback_plan="Restore BCD from backup or delete created entry.",
                report_path=self.gate.validation_report_path,
                target_path=self.gate.allowed_lab_dir,
                require_rollback_plan=True,
                require_report=True,
                require_target_in_lab_dir=True,
            )
        return self.runner.run(command, elevated_required=elevated_required, check=check)


@dataclass(slots=True)
class CommandBasedBcdBackend:
    """Command-based BCD backend built from builder + executor."""

    builder: BcdCommandBuilder
    executor: RunnerBcdExecutor
    allow_experimental_linux_chain: bool

    def export_backup(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.executor.execute(self.builder.export_backup(path), elevated_required=True)
        return path

    def create_entry(self, description: str) -> BcdEntry:
        if not self.allow_experimental_linux_chain:
            raise UnsupportedBootChainError(
                "Linux boot-chain entry generation is disabled. "
                "Use dry-run planning or enable explicit experimental mode."
            )

        warnings.warn(
            (
                "BCDEdit Linux boot-chain behavior is experimental. "
                "Copied Windows loader entries may require manual correction and "
                "validation in Windows VM before real use."
            ),
            ExperimentalBootChainWarning,
            stacklevel=2,
        )

        result = self.executor.execute(
            self.builder.copy_current_entry(description),
            elevated_required=True,
        )
        guid = self._extract_guid(result.stdout)
        return BcdEntry(guid=guid, description=description, loader_path=None)

    def set_entry_device(self, guid: str, device: str) -> None:
        self.executor.execute(self.builder.set_device(guid, device), elevated_required=True)

    def set_entry_path(self, guid: str, loader_path: str) -> None:
        self.executor.execute(self.builder.set_path(guid, loader_path), elevated_required=True)

    def add_to_display_order(self, guid: str) -> None:
        self.executor.execute(self.builder.add_to_display_order(guid), elevated_required=True)

    def delete_entry(self, guid: str) -> None:
        self.executor.execute(self.builder.delete_entry(guid), elevated_required=True)

    def _extract_guid(self, output: str) -> str:
        match = _GUID_RE.search(output)
        if not match:
            raise BcdOperationError("Could not parse GUID from bcdedit output.")
        return match.group(0)


@dataclass(slots=True)
class FakeBcdBackend:
    """In-memory BCD backend for tests and non-Windows dry runs."""

    last_guid: int = 0
    entries: dict[str, BcdEntry] = field(default_factory=dict)
    backups: list[Path] = field(default_factory=list)
    display_order: list[str] = field(default_factory=list)

    def export_backup(self, path: Path) -> Path:
        self.backups.append(path)
        return path

    def create_entry(self, description: str) -> BcdEntry:
        self.last_guid += 1
        guid = f"{{00000000-0000-0000-0000-{self.last_guid:012d}}}"
        entry = BcdEntry(guid=guid, description=description, loader_path=None)
        self.entries[guid] = entry
        return entry

    def set_entry_device(self, guid: str, device: str) -> None:
        if guid not in self.entries:
            raise BcdOperationError(f"Unknown GUID: {guid}")

    def set_entry_path(self, guid: str, loader_path: str) -> None:
        if guid not in self.entries:
            raise BcdOperationError(f"Unknown GUID: {guid}")
        entry = self.entries[guid]
        self.entries[guid] = BcdEntry(guid=entry.guid, description=entry.description, loader_path=loader_path)

    def add_to_display_order(self, guid: str) -> None:
        if guid not in self.entries:
            raise BcdOperationError(f"Unknown GUID: {guid}")
        self.display_order.append(guid)

    def delete_entry(self, guid: str) -> None:
        self.entries.pop(guid, None)
        if guid in self.display_order:
            self.display_order.remove(guid)


def create_windows_bcd_backend(
    runner: CommandRunner,
    *,
    gate: RealWindowsOpsGate,
) -> BcdBackend:
    """Create a real Windows BCD backend."""
    return CommandBasedBcdBackend(
        builder=BcdCommandBuilder(),
        executor=RunnerBcdExecutor(runner=runner, gate=gate),
        allow_experimental_linux_chain=True,
    )


def create_dry_run_bcd_backend(runner: CommandRunner) -> BcdBackend:
    """Create a dry-run backend that only validates command formation."""
    return CommandBasedBcdBackend(
        builder=BcdCommandBuilder(),
        executor=RunnerBcdExecutor(runner=runner, gate=None),
        allow_experimental_linux_chain=True,
    )
