"""Secure Boot validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from linux_vhd_launcher.errors import SecureBootChainError
from linux_vhd_launcher.models import LinuxDistribution


@dataclass(slots=True)
class SecureBootHelper:
    """Validates presence of expected Secure Boot chain files."""

    required_files: tuple[str, ...] = ("EFI/BOOT/BOOTX64.EFI", "EFI/BOOT/grubx64.efi")

    def verify_boot_files(self, staging_root: Path, distro: LinuxDistribution) -> list[str]:
        """Return warnings for missing files or unsupported distro metadata."""
        warnings: list[str] = []
        missing = [name for name in self.required_files if not (staging_root / name).exists()]
        if missing:
            raise SecureBootChainError(
                "Missing secure boot files: " + ", ".join(missing)
            )
        if not distro.secure_boot_supported:
            warnings.append(
                "Selected distribution is not marked as Secure Boot-compatible in catalog."
            )
        return warnings
