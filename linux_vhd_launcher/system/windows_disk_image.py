"""Windows ISO mount helpers used by live payload inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from linux_vhd_launcher.errors import UnsupportedPlatformError
from linux_vhd_launcher.system.runner import CommandRunner
from linux_vhd_launcher.system.windows_privileges import is_windows_platform


@dataclass(slots=True)
class MountedDiskImage:
    """Mounted image descriptor."""

    image_path: Path
    mount_point: Path


class DiskImageMounter(Protocol):
    """Protocol for mounting ISO images."""

    def mount_read_only(self, image_path: Path) -> MountedDiskImage:
        """Mount image and return filesystem mount point."""
        ...

    def dismount(self, mounted: MountedDiskImage) -> None:
        """Dismount image."""
        ...


@dataclass(slots=True)
class PowerShellDiskImageMounter:
    """Mounts/dismounts images using PowerShell Mount-DiskImage."""

    runner: CommandRunner

    def mount_read_only(self, image_path: Path) -> MountedDiskImage:
        if not is_windows_platform():
            raise UnsupportedPlatformError("Mount-DiskImage is available only on Windows.")

        escaped = _escape_ps_single_quoted(str(image_path))
        command = (
            f"$img = Mount-DiskImage -ImagePath '{escaped}' -PassThru -Access ReadOnly; "
            "$dl = ($img | Get-Volume | Select-Object -First 1 -ExpandProperty DriveLetter); "
            "if ($null -eq $dl -or $dl -eq '') { exit 77 }; "
            'Write-Output ("{0}:\\" -f $dl)'
        )

        result = self.runner.run(
            ["powershell", "-NoProfile", "-Command", command],
            elevated_required=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Mount-DiskImage failed for {image_path}: {result.stderr.strip() or result.stdout.strip()}"
            )

        mount_raw = result.stdout.strip().splitlines()[-1].strip()
        if not mount_raw:
            raise RuntimeError(f"Unable to determine mounted drive for {image_path}")

        return MountedDiskImage(image_path=image_path, mount_point=Path(mount_raw))

    def dismount(self, mounted: MountedDiskImage) -> None:
        escaped = _escape_ps_single_quoted(str(mounted.image_path))
        command = f"Dismount-DiskImage -ImagePath '{escaped}'"
        result = self.runner.run(
            ["powershell", "-NoProfile", "-Command", command],
            elevated_required=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Dismount-DiskImage failed for {mounted.image_path}: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )


@dataclass(slots=True)
class FakeDiskImageMounter:
    """Test fake mounter that maps ISO path to local extracted directory."""

    mapping: dict[Path, Path]

    def mount_read_only(self, image_path: Path) -> MountedDiskImage:
        key = image_path.resolve()
        if key not in self.mapping:
            raise FileNotFoundError(f"No fake mount mapping configured for {image_path}")
        return MountedDiskImage(image_path=image_path, mount_point=self.mapping[key])

    def dismount(self, mounted: MountedDiskImage) -> None:
        del mounted


def _escape_ps_single_quoted(value: str) -> str:
    return value.replace("'", "''")
