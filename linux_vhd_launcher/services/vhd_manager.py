"""VHD orchestration service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from linux_vhd_launcher.errors import InsufficientSpaceError, VhdOperationError
from linux_vhd_launcher.models import VhdSpec
from linux_vhd_launcher.system.windows_vhd import VhdBackend


@dataclass(slots=True)
class VHDManager:
    """Service to validate space and manage VHD lifecycle."""

    backend: VhdBackend

    def check_free_space(self, target_path: Path, required_gb: int) -> None:
        """Ensure target filesystem has enough free space."""
        required_bytes = required_gb * 1024 * 1024 * 1024
        free_bytes = self.backend.get_free_space(target_path)
        if free_bytes < required_bytes:
            raise InsufficientSpaceError(
                f"Need {required_gb} GiB, available {free_bytes / (1024 ** 3):.2f} GiB."
            )

    def create(self, spec: VhdSpec) -> None:
        """Create a VHD/VHDX file."""
        try:
            spec.path.parent.mkdir(parents=True, exist_ok=True)
            self.backend.create_vhd(spec)
        except Exception as exc:
            raise VhdOperationError(f"Failed to create VHD: {exc}") from exc

    def attach(self, path: Path) -> None:
        """Attach VHD/VHDX."""
        try:
            self.backend.attach_vhd(path)
        except Exception as exc:
            raise VhdOperationError(f"Failed to attach VHD: {exc}") from exc

    def detach(self, path: Path) -> None:
        """Detach VHD/VHDX."""
        try:
            self.backend.detach_vhd(path)
        except Exception as exc:
            raise VhdOperationError(f"Failed to detach VHD: {exc}") from exc

    def cleanup_vhd_file(self, path: Path) -> None:
        """Best-effort cleanup of generated virtual disk file."""
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            raise VhdOperationError(f"Failed to remove VHD file: {exc}") from exc
