"""Experimental live boot registration strategies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from linux_vhd_launcher.errors import UnsafeRealOperationError, UnsupportedPlatformError
from linux_vhd_launcher.models import LiveVhdLayout
from linux_vhd_launcher.system.runner import CommandResult, CommandRunner
from linux_vhd_launcher.system.windows_privileges import is_admin, is_windows_platform
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate

_GUID_RE = re.compile(r"\{[0-9a-fA-F\-]+\}")


@dataclass(slots=True)
class LiveRegistrationRequest:
    """Inputs for boot registration attempt."""

    layout: LiveVhdLayout
    report_dir: Path
    lab_dir: Path
    dry_run: bool
    execute_real_windows_ops: bool
    confirmation_token: bool
    confirm_vm_snapshot: bool


@dataclass(slots=True)
class LiveRegistrationOutcome:
    """Result of registration strategy execution."""

    strategy: str
    status: Literal["planned", "registration_blocked", "registration_experimental_done"]
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_guid: str | None = None
    backup_path: Path | None = None
    executed_commands: list[CommandResult] = field(default_factory=list)
    rollback_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "created_guid": self.created_guid,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "executed_commands": [
                {
                    "command": list(item.command),
                    "returncode": item.returncode,
                    "stdout": item.stdout,
                    "stderr": item.stderr,
                }
                for item in self.executed_commands
            ],
            "rollback_actions": self.rollback_actions,
        }


class LiveBootRegistrationStrategy(Protocol):
    """Protocol for boot registration strategy implementations."""

    name: str

    def register(self, request: LiveRegistrationRequest) -> LiveRegistrationOutcome:
        """Perform registration action or return explicit blocker."""
        ...


@dataclass(slots=True)
class BlockedUnsupportedStrategy:
    """Explicit blocker strategy when path is unsupported or unconfirmed."""

    reason: str
    name: str = "blocked"

    def register(self, request: LiveRegistrationRequest) -> LiveRegistrationOutcome:
        del request
        return LiveRegistrationOutcome(
            strategy=self.name,
            status="registration_blocked",
            blockers=[self.reason],
            warnings=["No BCD mutation executed."],
        )


@dataclass(slots=True)
class FirmwareStoreStrategy:
    """Placeholder for firmware-store based experiments."""

    name: str = "firmware"

    def register(self, request: LiveRegistrationRequest) -> LiveRegistrationOutcome:
        del request
        return LiveRegistrationOutcome(
            strategy=self.name,
            status="registration_blocked",
            blockers=[
                "Firmware-store strategy is not implemented in this demo. Behavior is not confirmed."
            ],
            warnings=[
                "не подтверждено: UEFI firmware visibility of EFI partition inside VHDX file on NTFS"
            ],
        )


@dataclass(slots=True)
class BcdBootMgrStrategy:
    """Experimental BCDEdit-based registration strategy."""

    allow_unconfirmed_direct_chain: bool = False
    name: str = "bootmgr"

    def register(self, request: LiveRegistrationRequest) -> LiveRegistrationOutcome:
        report_dir = request.report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        baseline_before = report_dir / "bcd_baseline_before.txt"
        baseline_after = report_dir / "bcd_baseline_after.txt"
        backup_path = report_dir / "bcd_backup_live_registration.bcd"

        if not self.allow_unconfirmed_direct_chain:
            return LiveRegistrationOutcome(
                strategy=self.name,
                status="registration_blocked",
                blockers=[
                    "Direct BCD -> Linux EFI loader inside VHD/VHDX is not confirmed by documentation/tests."
                ],
                warnings=[
                    "Planned experimental commands were generated but not executed.",
                    "Do not claim bootability without manual reboot validation.",
                ],
            )

        if request.dry_run:
            return LiveRegistrationOutcome(
                strategy=self.name,
                status="planned",
                warnings=["Dry-run: BCD commands not executed."],
            )

        if not request.confirm_vm_snapshot:
            raise UnsafeRealOperationError("register-bcd requires --confirm-vm-snapshot")
        if not is_windows_platform():
            raise UnsupportedPlatformError("register-bcd real mode is supported only on Windows")
        if not is_admin():
            raise UnsafeRealOperationError("register-bcd real mode requires administrator rights")

        gate = RealWindowsOpsGate(
            execute_real_windows_ops=request.execute_real_windows_ops,
            confirmation_token=request.confirmation_token,
            dry_run=False,
            backup_path=backup_path,
            allowed_lab_dir=request.lab_dir,
            validation_report_path=request.report_dir / "demo_report.json",
        )
        gate.assert_allowed(
            operation="demo live register-bcd",
            rollback_plan="Delete temporary GUID and use bcdedit /import backup in emergency mode.",
            report_path=request.report_dir / "demo_report.json",
            target_path=request.layout.vhd_path,
            require_rollback_plan=True,
            require_report=True,
            require_target_in_lab_dir=True,
        )

        runner = CommandRunner(dry_run=False)
        outcome = LiveRegistrationOutcome(
            strategy=self.name,
            status="registration_experimental_done",
            backup_path=backup_path,
            warnings=[
                "Experimental registration done. Bootability remains unverified until manual reboot test."
            ],
        )

        enum_before = runner.run(["bcdedit", "/enum", "all"], elevated_required=True, check=True)
        baseline_before.write_text(enum_before.stdout, encoding="utf-8")
        outcome.executed_commands.append(enum_before)

        export_cmd = runner.run(["bcdedit", "/export", str(backup_path)], elevated_required=True, check=True)
        outcome.executed_commands.append(export_cmd)

        copy_cmd = runner.run(
            ["bcdedit", "/copy", "{current}", "/d", "LinuxVHDLauncher Live (Experimental)"],
            elevated_required=True,
            check=True,
        )
        outcome.executed_commands.append(copy_cmd)
        guid = _extract_guid(copy_cmd.stdout)
        outcome.created_guid = guid

        try:
            vhd_device = f"vhd=[locate]{request.layout.vhd_path}"
            set_device = runner.run(
                ["bcdedit", "/set", guid, "device", vhd_device],
                elevated_required=True,
                check=True,
            )
            outcome.executed_commands.append(set_device)
            set_osdevice = runner.run(
                ["bcdedit", "/set", guid, "osdevice", vhd_device],
                elevated_required=True,
                check=True,
            )
            outcome.executed_commands.append(set_osdevice)
            set_path = runner.run(
                [
                    "bcdedit",
                    "/set",
                    guid,
                    "path",
                    request.layout.efi_loader_path.replace("/", "\\"),
                ],
                elevated_required=True,
                check=True,
            )
            outcome.executed_commands.append(set_path)

            enum_after = runner.run(["bcdedit", "/enum", "all"], elevated_required=True, check=True)
            baseline_after.write_text(enum_after.stdout, encoding="utf-8")
            outcome.executed_commands.append(enum_after)
        except Exception:
            rollback_errors: list[str] = []
            try:
                runner.run(["bcdedit", "/delete", guid, "/f"], elevated_required=True, check=False)
                outcome.rollback_actions.append(f"deleted temporary GUID {guid}")
            except Exception as exc:  # noqa: BLE001
                rollback_errors.append(str(exc))

            if rollback_errors:
                outcome.rollback_actions.extend(rollback_errors)
            raise

        manifest = {
            "strategy": self.name,
            "guid": outcome.created_guid,
            "backup": str(backup_path),
            "vhd": str(request.layout.vhd_path),
        }
        (request.report_dir / "live_registration_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        return outcome


def choose_registration_strategy(
    name: str,
    *,
    allow_unconfirmed_direct_chain: bool = False,
) -> LiveBootRegistrationStrategy:
    """Resolve strategy by CLI selector."""
    value = name.lower()
    if value == "blocked":
        return BlockedUnsupportedStrategy(reason="Registration explicitly blocked by operator.")
    if value == "firmware":
        return FirmwareStoreStrategy()
    if value == "bootmgr":
        return BcdBootMgrStrategy(allow_unconfirmed_direct_chain=allow_unconfirmed_direct_chain)
    if value == "auto":
        return BlockedUnsupportedStrategy(
            reason=(
                "Auto strategy selected blocked mode because direct Linux live chain via BCD is not confirmed."
            )
        )
    raise ValueError(f"Unknown strategy: {name}")


def _extract_guid(output: str) -> str:
    match = _GUID_RE.search(output)
    if not match:
        raise RuntimeError("Could not parse GUID from bcdedit output")
    return match.group(0)
