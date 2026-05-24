"""Experimental live boot registration strategies."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from linux_vhd_launcher.errors import UnsafeRealOperationError, UnsupportedPlatformError
from linux_vhd_launcher.models import EspStagingPlan, LiveVhdLayout, StagedEfiFile
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
    allow_known_failed_strategy: bool = False
    allow_esp_write: bool = False
    allow_firmware_entry: bool = False
    allow_secure_boot_experiment: bool = False


@dataclass(slots=True)
class LiveRegistrationOutcome:
    """Result of registration strategy execution."""

    strategy: str
    status: Literal[
        "planned",
        "registration_blocked",
        "registration_experimental_done",
        "registration_experimental_done_but_boot_failed",
        "registration_failed",
    ]
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_guid: str | None = None
    backup_path: Path | None = None
    known_failed_strategy: str | None = None
    esp_staging_plan: EspStagingPlan | None = None
    planned_commands: list[list[str]] = field(default_factory=list)
    executed_commands: list[CommandResult] = field(default_factory=list)
    unregister_command: list[str] | None = None
    rollback_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "created_guid": self.created_guid,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "known_failed_strategy": self.known_failed_strategy,
            "esp_staging_plan": (
                self.esp_staging_plan.to_dict() if self.esp_staging_plan is not None else None
            ),
            "planned_commands": [list(item) for item in self.planned_commands],
            "executed_commands": [
                {
                    "command": list(item.command),
                    "returncode": item.returncode,
                    "stdout": item.stdout,
                    "stderr": item.stderr,
                }
                for item in self.executed_commands
            ],
            "unregister_command": self.unregister_command,
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
class FirmwareEfiStagedDryRunStrategy:
    """Dry-run-only placeholder for firmware/ESP-staged experiments."""

    name: str = "firmware-efi-staged"

    def register(self, request: LiveRegistrationRequest) -> LiveRegistrationOutcome:
        staged_dir = "\\EFI\\LinuxVHDLauncher\\ubuntu-live\\"
        staged_files = [
            StagedEfiFile(
                source=f"{request.layout.vhd_path}::/EFI/BOOT/BOOTX64.EFI",
                destination=f"{staged_dir}BOOTX64.EFI",
                sha256=None,
                required=True,
            ),
            StagedEfiFile(
                source=f"{request.layout.vhd_path}::/EFI/BOOT/grubx64.efi",
                destination=f"{staged_dir}grubx64.efi",
                sha256=None,
                required=True,
            ),
            StagedEfiFile(
                source=f"{request.layout.vhd_path}::/EFI/BOOT/grub.cfg",
                destination=f"{staged_dir}grub.cfg",
                sha256=None,
                required=True,
            ),
        ]
        blockers = [
            "Documented BCDEdit flow for creating generic firmware EFI app entry is not confirmed in this project.",
            "BCD/firmware reference to EFI binary inside VHDX file is not confirmed.",
        ]
        rollback_steps = [
            "bcdedit /delete {GUID} /f (if firmware/Bcd entry created)",
            f"Remove-Item -Recurse -Force <ESP>\\{staged_dir.strip('\\')}",
            "mountvol <ESP_LETTER>: /d",
        ]
        esp_plan = EspStagingPlan(
            esp_mount_letter="S",
            staged_dir=staged_dir,
            files=staged_files,
            requires_esp_write=True,
            secure_boot_warning=(
                "Secure Boot path is unverified. Do not claim success without reboot evidence; "
                "shim/signature compatibility remains unknown."
            ),
            rollback_steps=rollback_steps,
            blockers=blockers,
        )
        planned = [
            ["powershell", "-NoProfile", "Mount-DiskImage -ImagePath <vhd-path> -PassThru"],
            ["bcdedit", "/enum", "firmware"],
            ["mountvol", "S:", "/s"],
            ["powershell", "-NoProfile", "Get-Volume -FileSystemLabel ESP"],
            ["copy", "<vhd-efi>\\BOOTX64.EFI", f"S:{staged_dir}BOOTX64.EFI"],
            ["copy", "<vhd-efi>\\grubx64.efi", f"S:{staged_dir}grubx64.efi"],
            ["copy", "<vhd-efi>\\grub.cfg", f"S:{staged_dir}grub.cfg"],
            ["bcdedit", "/create", "/d", "LinuxVHDLauncher Firmware EFI EXPERIMENT", "/application", "bootapp"],
            ["bcdedit", "/set", "{GUID}", "path", f"{staged_dir}BOOTX64.EFI"],
            ["bcdedit", "/displayorder", "{GUID}", "/addlast"],
            ["mountvol", "S:", "/d"],
        ]
        if not request.dry_run and (
            not request.allow_esp_write
            or not request.allow_firmware_entry
            or not request.allow_secure_boot_experiment
        ):
            return LiveRegistrationOutcome(
                strategy=self.name,
                status="registration_blocked",
                blockers=[
                    "firmware-efi-staged real mode requires --allow-esp-write, "
                    "--allow-firmware-entry, and --allow-secure-boot-experiment."
                ],
                warnings=["No ESP mutation executed."],
                planned_commands=planned,
                esp_staging_plan=esp_plan,
            )
        if not request.dry_run:
            return LiveRegistrationOutcome(
                strategy=self.name,
                status="registration_blocked",
                blockers=[
                    "firmware-efi-staged real mode remains blocked in this release until "
                    "documented firmware-entry creation path is validated."
                ],
                warnings=["No ESP mutation executed."],
                planned_commands=planned,
                esp_staging_plan=esp_plan,
            )
        return LiveRegistrationOutcome(
            strategy=self.name,
            status="planned",
            warnings=[
                "Dry-run only: firmware/ESP staging plan generated.",
                "Real ESP mutation requires separate explicit gated command.",
            ],
            planned_commands=planned,
            esp_staging_plan=esp_plan,
            blockers=blockers,
        )


@dataclass(slots=True)
class BcdBootMgrStrategy:
    """Experimental BCDEdit-based registration strategy."""

    name: str = "bootmgr"
    allow_unconfirmed_direct_chain: bool = False
    runner_factory: Callable[[], CommandRunner] = CommandRunner
    known_failed_strategy_id: str | None = None

    def register(self, request: LiveRegistrationRequest) -> LiveRegistrationOutcome:
        report_dir = request.report_dir
        if not report_dir.exists() or not report_dir.is_dir():
            raise UnsafeRealOperationError("register-bcd requires existing --report-dir directory.")

        baseline_before = report_dir / "bcd_baseline_before.txt"
        baseline_before_fw = report_dir / "bcd_baseline_before_firmware.txt"
        baseline_after = report_dir / "bcd_baseline_after.txt"
        baseline_after_fw = report_dir / "bcd_baseline_after_firmware.txt"
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

        if self.known_failed_strategy_id and not request.allow_known_failed_strategy:
            return LiveRegistrationOutcome(
                strategy=self.name,
                status="registration_blocked",
                blockers=[
                    "This strategy is known-failed from reboot evidence. "
                    "Use --allow-known-failed-strategy to run it again in disposable VM only."
                ],
                warnings=["No BCD mutation executed."],
                known_failed_strategy=self.known_failed_strategy_id,
            )

        vhd_device = _format_vhd_device(request.layout.vhd_path)
        planned_commands = _planned_experimental_commands(
            backup_path=backup_path,
            vhd_device=vhd_device,
            efi_path=request.layout.efi_loader_path.replace("/", "\\"),
        )

        if request.dry_run:
            return LiveRegistrationOutcome(
                strategy=self.name,
                status="planned",
                warnings=["Dry-run: BCD commands not executed."],
                planned_commands=planned_commands,
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

        runner = self.runner_factory()
        success_status: Literal[
            "registration_experimental_done",
            "registration_experimental_done_but_boot_failed",
        ] = (
            "registration_experimental_done_but_boot_failed"
            if self.known_failed_strategy_id
            else "registration_experimental_done"
        )

        outcome = LiveRegistrationOutcome(
            strategy=self.name,
            status=success_status,
            backup_path=backup_path,
            known_failed_strategy=self.known_failed_strategy_id,
            planned_commands=planned_commands,
            warnings=[
                "Experimental registration done. Bootability remains unverified until manual reboot test.",
                "Microsoft documents Native Boot VHD(X) for Windows entries. Linux chain is experimental and unverified.",
            ],
        )

        guid: str | None = None
        try:
            enum_before = _run_and_collect(runner, outcome, ["bcdedit", "/enum", "all"])
            baseline_before.write_text(enum_before.stdout, encoding="utf-8")

            enum_before_firmware = _run_and_collect(runner, outcome, ["bcdedit", "/enum", "firmware"])
            baseline_before_fw.write_text(enum_before_firmware.stdout, encoding="utf-8")

            _run_and_collect(runner, outcome, ["bcdedit", "/export", str(backup_path)])

            copy_cmd = _run_and_collect(
                runner,
                outcome,
                ["bcdedit", "/copy", "{current}", "/d", "LinuxVHDLauncher Ubuntu Live VHDX EXPERIMENT"],
            )
            guid = _extract_guid(copy_cmd.stdout)
            outcome.created_guid = guid

            _run_and_collect(runner, outcome, ["bcdedit", "/set", guid, "device", vhd_device])
            _run_and_collect(runner, outcome, ["bcdedit", "/set", guid, "osdevice", vhd_device])
            _run_and_collect(
                runner,
                outcome,
                ["bcdedit", "/set", guid, "path", request.layout.efi_loader_path.replace("/", "\\")],
            )
            _run_and_collect(runner, outcome, ["bcdedit", "/displayorder", guid, "/addlast"])

            enum_after = _run_and_collect(runner, outcome, ["bcdedit", "/enum", "all"])
            baseline_after.write_text(enum_after.stdout, encoding="utf-8")

            enum_after_firmware = _run_and_collect(runner, outcome, ["bcdedit", "/enum", "firmware"])
            baseline_after_fw.write_text(enum_after_firmware.stdout, encoding="utf-8")
        except Exception as exc:
            if guid is not None:
                delete_result = runner.run(
                    ["bcdedit", "/delete", guid, "/f"],
                    elevated_required=True,
                    check=False,
                )
                outcome.executed_commands.append(delete_result)
                outcome.rollback_actions.append(f"bcdedit /delete {guid} /f")
            outcome.status = "registration_failed"
            outcome.blockers.append(str(exc))
            outcome.warnings.append("Original command failure preserved in blockers/executed command evidence.")
            return outcome

        outcome.unregister_command = ["bcdedit", "/delete", guid, "/f"] if guid is not None else None
        manifest = {
            "strategy": self.name,
            "guid": outcome.created_guid,
            "backup": str(backup_path),
            "vhd": str(request.layout.vhd_path),
            "unregister_command": outcome.unregister_command,
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
    if value == "bootmgr-experimental-vhd":
        return BcdBootMgrStrategy(
            name="bootmgr-experimental-vhd",
            allow_unconfirmed_direct_chain=True,
            known_failed_strategy_id="copied-current-osloader-vhd",
        )
    if value == "firmware-efi-staged":
        return FirmwareEfiStagedDryRunStrategy()
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


def _format_vhd_device(vhd_path: Path) -> str:
    raw = str(vhd_path).replace("/", "\\")
    drive_match = re.match(r"^([a-zA-Z]):\\", raw)
    if drive_match:
        drive = drive_match.group(1).upper()
        return f"vhd=[{drive}:]{raw[2:]}"
    return f"vhd=[locate]{raw}"


def _run_and_collect(
    runner: CommandRunner,
    outcome: LiveRegistrationOutcome,
    command: list[str],
) -> CommandResult:
    result = runner.run(command, elevated_required=True, check=False)
    outcome.executed_commands.append(result)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(command)} "
            f"stdout={result.stdout.strip()} stderr={result.stderr.strip()}"
        )
    return result


def _planned_experimental_commands(
    *,
    backup_path: Path,
    vhd_device: str,
    efi_path: str,
) -> list[list[str]]:
    return [
        ["bcdedit", "/enum", "all"],
        ["bcdedit", "/enum", "firmware"],
        ["bcdedit", "/export", str(backup_path)],
        ["bcdedit", "/copy", "{current}", "/d", "LinuxVHDLauncher Ubuntu Live VHDX EXPERIMENT"],
        ["bcdedit", "/set", "{GUID}", "device", vhd_device],
        ["bcdedit", "/set", "{GUID}", "osdevice", vhd_device],
        ["bcdedit", "/set", "{GUID}", "path", efi_path],
        ["bcdedit", "/displayorder", "{GUID}", "/addlast"],
        ["bcdedit", "/enum", "all"],
        ["bcdedit", "/enum", "firmware"],
    ]
