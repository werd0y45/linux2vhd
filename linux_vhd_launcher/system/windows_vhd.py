"""Windows VHD backends and abstractions."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from linux_vhd_launcher.errors import UnsupportedPlatformError, VhdOperationError
from linux_vhd_launcher.models import VhdSpec
from linux_vhd_launcher.system.runner import CommandRunner
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate
from linux_vhd_launcher.system.windows_virtdisk_ctypes import (
    ATTACH_VIRTUAL_DISK_FLAG_NONE,
    CREATE_VIRTUAL_DISK_FLAG_NONE,
    CREATE_VIRTUAL_DISK_PARAMETERS,
    CREATE_VIRTUAL_DISK_PARAMETERS_VERSION_2,
    DETACH_VIRTUAL_DISK_FLAG_NONE,
    OPEN_VIRTUAL_DISK_FLAG_NONE,
    OPEN_VIRTUAL_DISK_PARAMETERS,
    OPEN_VIRTUAL_DISK_VERSION_1,
    VIRTUAL_DISK_ACCESS_ALL,
    VIRTUAL_STORAGE_TYPE,
    VIRTUAL_STORAGE_TYPE_DEVICE_VHD,
    VIRTUAL_STORAGE_TYPE_DEVICE_VHDX,
    VIRTUAL_STORAGE_TYPE_VENDOR_MICROSOFT,
    WinVirtDiskApi,
)

logger = logging.getLogger(__name__)


class VirtDiskApiProtocol(Protocol):
    """Protocol for injectable virtdisk API adapters."""

    def create_virtual_disk(
        self,
        *,
        storage_type: VIRTUAL_STORAGE_TYPE,
        path: Path,
        access_mask: int,
        create_flags: int,
        parameters: CREATE_VIRTUAL_DISK_PARAMETERS,
    ) -> int:
        """Create a virtual disk and return handle."""
        ...

    def open_virtual_disk(
        self,
        *,
        storage_type: VIRTUAL_STORAGE_TYPE,
        path: Path,
        access_mask: int,
        open_flags: int,
        parameters: OPEN_VIRTUAL_DISK_PARAMETERS,
    ) -> int:
        """Open virtual disk and return handle."""
        ...

    def attach_virtual_disk(self, *, handle: int, flags: int) -> None:
        """Attach opened virtual disk handle."""
        ...

    def detach_virtual_disk(self, *, handle: int, flags: int) -> None:
        """Detach opened virtual disk handle."""
        ...

    def close_handle(self, handle: int) -> None:
        """Close handle returned by create/open APIs."""
        ...


class VhdBackend(Protocol):
    """Protocol for virtual disk operations."""

    def create_vhd(self, spec: VhdSpec) -> None:
        """Create VHD/VHDX according to spec."""
        ...

    def attach_vhd(self, path: Path) -> None:
        """Attach existing VHD/VHDX."""
        ...

    def detach_vhd(self, path: Path) -> None:
        """Detach attached VHD/VHDX."""
        ...

    def get_free_space(self, path: Path) -> int:
        """Return free bytes for hosting filesystem."""
        ...


@dataclass(slots=True)
class DiskPartVhdBackend:
    """diskpart-based implementation for initial Windows prototype."""

    runner: CommandRunner
    gate: RealWindowsOpsGate

    def create_vhd(self, spec: VhdSpec) -> None:
        self.gate.assert_allowed(
            operation="diskpart create vdisk",
            rollback_plan=f"Delete file {spec.path}",
            target_path=spec.path,
            require_rollback_plan=True,
            require_report=True,
            require_target_in_lab_dir=True,
        )
        if spec.format not in {"vhd", "vhdx"}:
            raise VhdOperationError(f"Unsupported VHD format: {spec.format}")
        max_mb = spec.size_gb * 1024
        script = "\n".join(
            [
                f'create vdisk file="{spec.path}" maximum={max_mb} type=expandable',
            ]
        )
        self._run_diskpart_script(script)

    def attach_vhd(self, path: Path) -> None:
        self.gate.assert_allowed(
            operation="diskpart attach vdisk",
            rollback_plan=f"Detach virtual disk {path}",
            target_path=path,
            require_rollback_plan=True,
            require_report=True,
            require_target_in_lab_dir=True,
        )
        script = "\n".join([f'select vdisk file="{path}"', "attach vdisk"])
        self._run_diskpart_script(script)

    def detach_vhd(self, path: Path) -> None:
        self.gate.assert_allowed(
            operation="diskpart detach vdisk",
            rollback_plan="n/a (detach is rollback terminal action)",
            target_path=path,
            require_rollback_plan=True,
            require_report=True,
            require_target_in_lab_dir=True,
        )
        script = "\n".join([f'select vdisk file="{path}"', "detach vdisk"])
        self._run_diskpart_script(script)

    def get_free_space(self, path: Path) -> int:
        target = path if path.is_dir() else path.parent
        usage = shutil.disk_usage(target)
        return usage.free

    def _run_diskpart_script(self, script: str) -> None:
        with NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write(script)
            script_path = Path(handle.name)

        try:
            self.runner.run(["diskpart", "/s", str(script_path)], elevated_required=True)
        finally:
            script_path.unlink(missing_ok=True)


@dataclass(slots=True)
class VirtualDiskApiBackend:
    """Skeleton backend for Win32 virtdisk API integration."""

    gate: RealWindowsOpsGate
    api: VirtDiskApiProtocol = field(default_factory=WinVirtDiskApi)

    def create_vhd(self, spec: VhdSpec) -> None:
        self._assert_platform_and_gate(
            "CreateVirtualDisk",
            rollback_plan=f"Delete file {spec.path}",
            target_path=spec.path,
        )
        handle = None
        try:
            handle = self.create_virtual_disk(spec)
        finally:
            if handle is not None:
                self.close_handle(handle)

    def attach_vhd(self, path: Path) -> None:
        self._assert_platform_and_gate(
            "AttachVirtualDisk",
            rollback_plan=f"Detach virtual disk {path}",
            target_path=path,
        )
        handle = self.open_virtual_disk(path)
        try:
            self.attach_virtual_disk(handle)
        finally:
            self.close_handle(handle)

    def detach_vhd(self, path: Path) -> None:
        self._assert_platform_and_gate(
            "DetachVirtualDisk",
            rollback_plan="n/a (detach is rollback terminal action)",
            target_path=path,
        )
        handle = self.open_virtual_disk(path)
        try:
            self.detach_virtual_disk(handle)
        finally:
            self.close_handle(handle)

    def get_free_space(self, path: Path) -> int:
        target = path if path.is_dir() else path.parent
        return shutil.disk_usage(target).free

    def create_virtual_disk(self, spec: VhdSpec) -> int:
        device_id = (
            VIRTUAL_STORAGE_TYPE_DEVICE_VHDX
            if spec.format == "vhdx"
            else VIRTUAL_STORAGE_TYPE_DEVICE_VHD
        )
        self._assert_platform_and_gate(
            "CreateVirtualDisk",
            rollback_plan=f"Delete file {spec.path}",
            target_path=spec.path,
        )
        storage_type = VIRTUAL_STORAGE_TYPE(
            DeviceId=device_id,
            VendorId=VIRTUAL_STORAGE_TYPE_VENDOR_MICROSOFT,
        )
        parameters = CREATE_VIRTUAL_DISK_PARAMETERS()
        parameters.Version = CREATE_VIRTUAL_DISK_PARAMETERS_VERSION_2
        parameters.Version2.MaximumSize = spec.size_gb * 1024 * 1024 * 1024
        # For VERSION_2, Microsoft requires VIRTUAL_DISK_ACCESS_NONE on CreateVirtualDisk.
        return self.api.create_virtual_disk(
            storage_type=storage_type,
            path=spec.path,
            access_mask=0,
            create_flags=CREATE_VIRTUAL_DISK_FLAG_NONE,
            parameters=parameters,
        )

    def open_virtual_disk(self, path: Path) -> int:
        self._assert_platform_and_gate(
            "OpenVirtualDisk",
            rollback_plan=f"Close and detach virtual disk {path}",
            target_path=path,
        )
        storage_type = VIRTUAL_STORAGE_TYPE(
            DeviceId=VIRTUAL_STORAGE_TYPE_DEVICE_VHDX,
            VendorId=VIRTUAL_STORAGE_TYPE_VENDOR_MICROSOFT,
        )
        parameters = OPEN_VIRTUAL_DISK_PARAMETERS()
        parameters.Version = OPEN_VIRTUAL_DISK_VERSION_1
        return self.api.open_virtual_disk(
            storage_type=storage_type,
            path=path,
            access_mask=VIRTUAL_DISK_ACCESS_ALL,
            open_flags=OPEN_VIRTUAL_DISK_FLAG_NONE,
            parameters=parameters,
        )

    def attach_virtual_disk(self, handle: int) -> None:
        self._assert_platform_and_gate(
            "AttachVirtualDisk",
            rollback_plan="DetachVirtualDisk on same handle/path",
            target_path=self.gate.allowed_lab_dir,
        )
        self.api.attach_virtual_disk(handle=handle, flags=ATTACH_VIRTUAL_DISK_FLAG_NONE)

    def detach_virtual_disk(self, handle: int) -> None:
        self._assert_platform_and_gate(
            "DetachVirtualDisk",
            rollback_plan="n/a (detach completes rollback)",
            target_path=self.gate.allowed_lab_dir,
        )
        self.api.detach_virtual_disk(handle=handle, flags=DETACH_VIRTUAL_DISK_FLAG_NONE)

    def close_handle(self, handle: int) -> None:
        self.api.close_handle(handle)

    def _assert_platform_and_gate(
        self,
        operation: str,
        *,
        rollback_plan: str,
        target_path: Path | None,
    ) -> None:
        if not self.gate.platform_checker():
            raise UnsupportedPlatformError(
                f"{operation} is available only on Windows in experimental validation mode."
            )
        self.gate.assert_allowed(
            operation=operation,
            rollback_plan=rollback_plan,
            target_path=target_path,
            require_rollback_plan=True,
            require_report=True,
            require_target_in_lab_dir=True,
        )


@dataclass(slots=True)
class FakeVhdBackend:
    """In-memory VHD backend for tests and Linux dry-run."""

    free_space_bytes: int
    created: list[Path] = field(default_factory=list)
    attached: set[Path] = field(default_factory=set)
    detached: list[Path] = field(default_factory=list)

    def create_vhd(self, spec: VhdSpec) -> None:
        self.created.append(spec.path)

    def attach_vhd(self, path: Path) -> None:
        self.attached.add(path)

    def detach_vhd(self, path: Path) -> None:
        self.detached.append(path)
        self.attached.discard(path)

    def get_free_space(self, path: Path) -> int:
        return self.free_space_bytes


@dataclass(slots=True)
class FakeVirtDiskApi:
    """Fake virtdisk API adapter for command-flow tests."""

    next_handle: int = 100
    created_paths: list[Path] = field(default_factory=list)
    opened_paths: list[Path] = field(default_factory=list)
    attached_handles: list[int] = field(default_factory=list)
    detached_handles: list[int] = field(default_factory=list)
    closed_handles: list[int] = field(default_factory=list)
    fail_create: bool = False
    fail_open: bool = False
    fail_attach: bool = False
    fail_detach: bool = False
    fail_close: bool = False

    def create_virtual_disk(
        self,
        *,
        storage_type: VIRTUAL_STORAGE_TYPE,
        path: Path,
        access_mask: int,
        create_flags: int,
        parameters: CREATE_VIRTUAL_DISK_PARAMETERS,
    ) -> int:
        del storage_type, access_mask, create_flags, parameters
        if self.fail_create:
            raise VhdOperationError("fake create failure")
        self.created_paths.append(path)
        self.next_handle += 1
        return self.next_handle

    def open_virtual_disk(
        self,
        *,
        storage_type: VIRTUAL_STORAGE_TYPE,
        path: Path,
        access_mask: int,
        open_flags: int,
        parameters: OPEN_VIRTUAL_DISK_PARAMETERS,
    ) -> int:
        del storage_type, access_mask, open_flags, parameters
        if self.fail_open:
            raise VhdOperationError("fake open failure")
        self.opened_paths.append(path)
        self.next_handle += 1
        return self.next_handle

    def attach_virtual_disk(self, *, handle: int, flags: int) -> None:
        del flags
        if self.fail_attach:
            raise VhdOperationError("fake attach failure")
        self.attached_handles.append(handle)

    def detach_virtual_disk(self, *, handle: int, flags: int) -> None:
        del flags
        if self.fail_detach:
            raise VhdOperationError("fake detach failure")
        self.detached_handles.append(handle)

    def close_handle(self, handle: int) -> None:
        if self.fail_close:
            raise VhdOperationError("fake close failure")
        self.closed_handles.append(handle)
