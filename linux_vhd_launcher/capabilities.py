"""Non-destructive backend capability scanners."""

from __future__ import annotations

import ctypes
import platform
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from linux_vhd_launcher.models import BackendCapability, CapabilityStatus, ProbeResult
from linux_vhd_launcher.system.windows_privileges import is_admin, is_windows_platform


class CapabilityScanner(Protocol):
    """Scanner protocol returning capabilities and probe results."""

    def scan(self) -> tuple[list[BackendCapability], list[ProbeResult]]:
        """Run non-destructive capability detection."""
        ...


@dataclass(slots=True)
class BcdCapabilityScanner:
    """Checks BCDEdit/BCDBoot command availability."""

    which: Callable[[str], str | None] = shutil.which

    def scan(self) -> tuple[list[BackendCapability], list[ProbeResult]]:
        bcdedit = self.which("bcdedit") is not None
        bcdboot = self.which("bcdboot") is not None
        capabilities = [
            BackendCapability(
                backend="bcd",
                capability="bcdedit",
                status="available" if bcdedit else "unavailable",
                reason=None if bcdedit else "bcdedit not found in PATH",
                docs_url="https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/bcd-boot-options-reference",
            ),
            BackendCapability(
                backend="bcd",
                capability="bcdboot",
                status="available" if bcdboot else "unavailable",
                reason=None if bcdboot else "bcdboot not found in PATH",
                docs_url="https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/bcdboot-command-line-options-techref-di",
            ),
        ]
        probes = [
            ProbeResult(
                id="probe.bcdedit.available",
                name="bcdedit in PATH",
                status="pass" if bcdedit else "fail",
                value=bcdedit,
                details=None if bcdedit else "bcdedit executable not discovered",
                source="PATH",
                command_preview=["bcdedit", "/?"],
            ),
            ProbeResult(
                id="probe.bcdboot.available",
                name="bcdboot in PATH",
                status="pass" if bcdboot else "fail",
                value=bcdboot,
                details=None if bcdboot else "bcdboot executable not discovered",
                source="PATH",
                command_preview=["bcdboot", "/?"],
            ),
        ]
        return capabilities, probes


@dataclass(slots=True)
class VhdCapabilityScanner:
    """Checks VHD command tooling availability."""

    which: Callable[[str], str | None] = shutil.which

    def scan(self) -> tuple[list[BackendCapability], list[ProbeResult]]:
        diskpart = self.which("diskpart") is not None
        capabilities = [
            BackendCapability(
                backend="vhd",
                capability="diskpart",
                status="available" if diskpart else "unavailable",
                reason=None if diskpart else "diskpart not found in PATH",
                docs_url="https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/diskpart",
            )
        ]
        probes = [
            ProbeResult(
                id="probe.diskpart.available",
                name="diskpart in PATH",
                status="pass" if diskpart else "fail",
                value=diskpart,
                details=None if diskpart else "diskpart executable not discovered",
                source="PATH",
                command_preview=["diskpart", "/?"],
            )
        ]
        return capabilities, probes


@dataclass(slots=True)
class PowerShellCapabilityScanner:
    """Checks PowerShell and key command availability."""

    which: Callable[[str], str | None] = shutil.which

    def _available_shell(self) -> str | None:
        return self.which("powershell") or self.which("pwsh")

    def scan(self) -> tuple[list[BackendCapability], list[ProbeResult]]:
        shell = self._available_shell()
        has_shell = shell is not None

        capabilities = [
            BackendCapability(
                backend="powershell",
                capability="powershell",
                status="available" if has_shell else "unavailable",
                reason=None if has_shell else "powershell/pwsh not found in PATH",
                docs_url="https://learn.microsoft.com/en-us/powershell/",
            ),
            BackendCapability(
                backend="powershell",
                capability="Confirm-SecureBootUEFI",
                status="unknown" if has_shell else "unavailable",
                reason="Requires PowerShell SecureBoot module on Windows host"
                if has_shell
                else "PowerShell unavailable",
                docs_url="https://learn.microsoft.com/en-us/powershell/module/secureboot/confirm-securebootuefi",
            ),
            BackendCapability(
                backend="powershell",
                capability="Get-BitLockerVolume",
                status="unknown" if has_shell else "unavailable",
                reason="Requires BitLocker module availability on Windows host"
                if has_shell
                else "PowerShell unavailable",
                docs_url="https://learn.microsoft.com/en-us/powershell/module/bitlocker/get-bitlockervolume",
            ),
            BackendCapability(
                backend="powershell",
                capability="Mount-DiskImage",
                status="unknown" if has_shell else "unavailable",
                reason="Requires Storage module availability on Windows host"
                if has_shell
                else "PowerShell unavailable",
                docs_url="https://learn.microsoft.com/en-us/powershell/module/storage/mount-diskimage",
            ),
            BackendCapability(
                backend="powershell",
                capability="Dismount-DiskImage",
                status="unknown" if has_shell else "unavailable",
                reason="Requires Storage module availability on Windows host"
                if has_shell
                else "PowerShell unavailable",
                docs_url="https://learn.microsoft.com/en-us/powershell/module/storage/dismount-diskimage",
            ),
        ]

        probes = [
            ProbeResult(
                id="probe.powershell.available",
                name="PowerShell shell in PATH",
                status="pass" if has_shell else "fail",
                value=shell if has_shell else False,
                details=None if has_shell else "powershell/pwsh executable not discovered",
                source="PATH",
                command_preview=[shell or "powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion"],
            )
        ]
        return capabilities, probes


@dataclass(slots=True)
class VirtdiskCapabilityScanner:
    """Checks virtdisk.dll availability via ctypes."""

    is_windows: Callable[[], bool] = is_windows_platform

    def scan(self) -> tuple[list[BackendCapability], list[ProbeResult]]:
        if not self.is_windows():
            capability = BackendCapability(
                backend="virtdisk",
                capability="virtdisk.dll",
                status="blocked",
                reason="Non-Windows platform",
                docs_url="https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/",
            )
            probe = ProbeResult(
                id="probe.virtdisk.dll",
                name="virtdisk.dll availability",
                status="not_applicable",
                value=None,
                details="virtdisk probing is not applicable on non-Windows hosts",
                source="platform",
                command_preview=None,
            )
            return [capability], [probe]

        try:
            win_dll = cast(Callable[[str], object], ctypes.WinDLL)  # type: ignore[attr-defined]
            win_dll("virtdisk.dll")
            available = True
            reason = None
            status: CapabilityStatus = "available"
        except OSError as exc:
            available = False
            reason = str(exc)
            status = "unavailable"

        capability = BackendCapability(
            backend="virtdisk",
            capability="virtdisk.dll",
            status=status,
            reason=reason,
            docs_url="https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/",
        )
        probe = ProbeResult(
            id="probe.virtdisk.dll",
            name="virtdisk.dll availability",
            status="pass" if available else "fail",
            value=available,
            details=reason,
            source="ctypes.WinDLL",
            command_preview=None,
        )
        return [capability], [probe]


@dataclass(slots=True)
class EnvironmentCapabilityScanner:
    """Checks platform/admin and dry-run capability."""

    is_windows: Callable[[], bool] = is_windows_platform
    is_admin_fn: Callable[[], bool] = is_admin

    def scan(self) -> tuple[list[BackendCapability], list[ProbeResult]]:
        windows = self.is_windows()
        admin = self.is_admin_fn()
        capabilities = [
            BackendCapability(
                backend="environment",
                capability="windows-platform",
                status="available" if windows else "blocked",
                reason=None if windows else "Running on non-Windows host",
                docs_url=None,
            ),
            BackendCapability(
                backend="environment",
                capability="admin-session",
                status="available" if admin else "blocked",
                reason=None if admin else "Administrator rights are required for real Windows ops",
                docs_url=None,
            ),
            BackendCapability(
                backend="dry-run",
                capability="dry-run-backend",
                status="available",
                reason="Always available for planning and safe validation",
                docs_url=None,
            ),
        ]
        probes = [
            ProbeResult(
                id="probe.platform.windows",
                name="Windows platform",
                status="pass" if windows else "warning",
                value=windows,
                details=None if windows else "Windows-only operations are blocked on this host",
                source="platform.system",
                command_preview=None,
            ),
            ProbeResult(
                id="probe.platform.admin",
                name="Administrator privileges",
                status="pass" if admin else "warning",
                value=admin,
                details=None if admin else "Admin privileges not detected",
                source="privilege check",
                command_preview=None,
            ),
            ProbeResult(
                id="probe.python.version",
                name="Python version",
                status="pass",
                value=platform.python_version(),
                details=None,
                source="platform.python_version",
                command_preview=None,
            ),
        ]
        return capabilities, probes


@dataclass(slots=True)
class FakeCapabilityScanner:
    """Test helper scanner returning precomputed results."""

    capabilities: list[BackendCapability]
    probes: list[ProbeResult]

    def scan(self) -> tuple[list[BackendCapability], list[ProbeResult]]:
        return list(self.capabilities), list(self.probes)


def run_capability_scanners(
    scanners: Sequence[CapabilityScanner] | None = None,
) -> tuple[list[BackendCapability], list[ProbeResult]]:
    """Run all scanners and flatten the results."""
    effective: list[CapabilityScanner]
    if scanners is not None:
        effective = list(scanners)
    else:
        effective = [
            EnvironmentCapabilityScanner(),
            BcdCapabilityScanner(),
            VhdCapabilityScanner(),
            PowerShellCapabilityScanner(),
            VirtdiskCapabilityScanner(),
        ]

    all_capabilities: list[BackendCapability] = []
    all_probes: list[ProbeResult] = []
    for scanner in effective:
        capabilities, probes = scanner.scan()
        all_capabilities.extend(capabilities)
        all_probes.extend(probes)
    return all_capabilities, all_probes
