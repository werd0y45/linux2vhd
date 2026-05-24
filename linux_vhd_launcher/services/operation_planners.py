"""Structured planning models for dry-run and Windows lab readiness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from linux_vhd_launcher.models import OperationPlan, PlannedStep, VhdSpec
from linux_vhd_launcher.system.windows_bcd import BcdCommandBuilder

BCD_DOCS_URL = (
    "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/"
    "bcdedit-command-line-options?view=windows-11"
)
ADD_BOOT_ENTRY_DOCS_URL = (
    "https://learn.microsoft.com/en-au/windows-hardware/drivers/devtest/adding-boot-entries"
)
BCDBOOT_DOCS_URL = (
    "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/"
    "bcdboot-command-line-options-techref-di?view=windows-11"
)
VHD_NATIVE_BOOT_DOCS_URL = (
    "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/"
    "boot-to-vhd--native-boot--add-a-virtual-hard-disk-to-the-boot-menu?view=windows-11"
)
VIRTDISK_DOCS_URL = "https://learn.microsoft.com/en-us/windows/win32/vstor/about-vhd"


@dataclass(slots=True)
class VhdOperationPlanner:
    """Builds a VHD lifecycle plan."""

    def build(self, vhd_spec: VhdSpec) -> OperationPlan:
        steps = [
            PlannedStep(
                id="vhd-create",
                title="Create virtual disk file",
                command_preview=["diskpart", "/s", "<generated-script>"],
                description=(
                    f"Create {vhd_spec.format.upper()} at {vhd_spec.path} "
                    f"with size {vhd_spec.size_gb} GiB."
                ),
                dangerous=True,
                rollback=f"Delete file {vhd_spec.path}",
                docs_url=VIRTDISK_DOCS_URL,
                prerequisites=["Windows admin session", "Validation lab directory available"],
                expected_result=f"Virtual disk file {vhd_spec.path.name} exists",
                rollback_action=f"Delete file {vhd_spec.path}",
                verification_action=f"Verify {vhd_spec.path} is removed after rollback",
                risk_level="high",
            ),
            PlannedStep(
                id="vhd-attach",
                title="Attach virtual disk",
                command_preview=["diskpart", "/s", "<generated-script>"],
                description="Attach created virtual disk to expose partitioning context.",
                dangerous=True,
                rollback=f"Detach virtual disk {vhd_spec.path}",
                docs_url=VIRTDISK_DOCS_URL,
                prerequisites=["Step vhd-create completed"],
                expected_result="Disk appears as attached in Disk Management",
                rollback_action=f"Detach virtual disk {vhd_spec.path}",
                verification_action="Confirm virtual disk no longer attached",
                risk_level="high",
            ),
            PlannedStep(
                id="vhd-detach",
                title="Detach virtual disk",
                command_preview=["diskpart", "/s", "<generated-script>"],
                description="Detach virtual disk after deployment and BCD planning steps.",
                dangerous=True,
                rollback=None,
                docs_url=VIRTDISK_DOCS_URL,
                prerequisites=["Step vhd-attach completed"],
                expected_result="Disk detaches successfully",
                rollback_action="n/a",
                verification_action="Confirm disk no longer present in attach list",
                risk_level="medium",
            ),
        ]
        return OperationPlan(
            title="VHD Operations Plan",
            target_platform="Windows",
            steps=steps,
            warnings=[
                "Disk operations require administrator privileges on Windows.",
                "DiskPart backend is transitional; virtdisk backend is still a skeleton.",
            ],
            dangerous=True,
            requires_admin=True,
            experimental=True,
        )


@dataclass(slots=True)
class BcdOperationPlanner:
    """Builds BCD operation plan with command previews."""

    command_builder: BcdCommandBuilder

    def build(
        self,
        *,
        description: str,
        device: str,
        loader_path: str,
        backup_path: Path,
    ) -> OperationPlan:
        steps = [
            PlannedStep(
                id="bcd-export",
                title="Export BCD backup",
                command_preview=list(self.command_builder.export_backup(backup_path)),
                description="Export current BCD store before any mutation.",
                dangerous=False,
                rollback=f"Import backup from {backup_path} if rollback is needed.",
                docs_url=BCD_DOCS_URL,
                prerequisites=["Windows admin session", "Lab snapshot exists"],
                expected_result="Backup file created successfully",
                rollback_action=f"Use bcdedit /import {backup_path}",
                verification_action="Validate backup file exists and has non-zero size",
                risk_level="low",
            ),
            PlannedStep(
                id="bcd-copy-current",
                title="Create new entry by copying current loader",
                command_preview=list(self.command_builder.copy_current_entry(description)),
                description=(
                    "Create experimental boot entry from {current}. "
                    "GUID must be captured from command output for follow-up steps."
                ),
                dangerous=True,
                rollback="Delete created entry via bcdedit /delete {guid} /f.",
                docs_url=ADD_BOOT_ENTRY_DOCS_URL,
                prerequisites=["Step bcd-export completed"],
                expected_result="Temporary GUID for copied entry is returned",
                rollback_action="Delete GUID and restore backup on failure",
                verification_action="Run bcdedit /enum and ensure GUID is present",
                risk_level="critical",
            ),
            PlannedStep(
                id="bcd-set-device",
                title="Set entry device",
                command_preview=list(self.command_builder.set_device("{new-guid}", device)),
                description="Bind entry to VHD-backed device path.",
                dangerous=True,
                rollback="Restore from backup or delete entry.",
                docs_url=BCD_DOCS_URL,
                prerequisites=["Step bcd-copy-current completed"],
                expected_result="Entry device points to expected VHD path",
                rollback_action="Delete entry and restore backup",
                verification_action="Validate entry element reflects expected device",
                risk_level="critical",
            ),
            PlannedStep(
                id="bcd-set-path",
                title="Set EFI loader path",
                command_preview=list(self.command_builder.set_path("{new-guid}", loader_path)),
                description="Configure EFI loader path for experimental Linux chain.",
                dangerous=True,
                rollback="Restore from backup or delete entry.",
                docs_url=BCD_DOCS_URL,
                prerequisites=["Step bcd-set-device completed"],
                expected_result="Entry path element is updated",
                rollback_action="Delete entry and restore backup",
                verification_action="Validate bcdedit output for path element",
                risk_level="critical",
            ),
            PlannedStep(
                id="bcd-display-order",
                title="Append new entry to boot menu",
                command_preview=list(self.command_builder.add_to_display_order("{new-guid}")),
                description="Expose entry in Windows Boot Manager menu.",
                dangerous=True,
                rollback="Remove entry from display order or delete it.",
                docs_url=BCD_DOCS_URL,
                prerequisites=["Step bcd-set-path completed", "Explicit displayorder opt-in"],
                expected_result="Displayorder includes entry at end",
                rollback_action="Remove from displayorder and delete temporary entry",
                verification_action="Re-read displayorder to confirm change",
                risk_level="critical",
            ),
        ]
        return OperationPlan(
            title="BCD Operations Plan",
            target_platform="Windows",
            steps=steps,
            warnings=[
                "Linux boot chain via Windows Boot Manager remains experimental.",
                "Native Boot to VHDX documentation is Windows-OS-centric, not Linux boot guarantee.",
            ],
            dangerous=True,
            requires_admin=True,
            experimental=True,
        )


@dataclass(slots=True)
class DeploymentOperationPlanner:
    """Builds deployment preparation plan."""

    def build(self, *, iso_path: Path, vhd_spec: VhdSpec) -> OperationPlan:
        del vhd_spec
        steps = [
            PlannedStep(
                id="deploy-validate-iso",
                title="Validate source ISO",
                command_preview=None,
                description=f"Validate ISO path and extension: {iso_path}",
                dangerous=False,
                rollback=None,
                docs_url=None,
                prerequisites=["ISO is present in accessible filesystem"],
                expected_result="ISO metadata can be parsed",
                rollback_action="n/a",
                verification_action="Confirm ISO file exists and extension is .iso",
                risk_level="low",
            ),
            PlannedStep(
                id="deploy-stage-boot-files",
                title="Stage EFI boot files (placeholder)",
                command_preview=None,
                description=(
                    "Prepare placeholder EFI/BOOT assets in staging area. "
                    "Real Linux filesystem deployment is not implemented yet."
                ),
                dangerous=False,
                rollback="Remove staging directory.",
                docs_url=BCDBOOT_DOCS_URL,
                prerequisites=["Step deploy-validate-iso completed"],
                expected_result="Staging placeholder files exist",
                rollback_action="Delete staging directory",
                verification_action="Confirm staging directory is cleaned on rollback",
                risk_level="medium",
            ),
            PlannedStep(
                id="deploy-verify-boot-chain",
                title="Verify boot chain files",
                command_preview=None,
                description="Check required EFI files exist before BCD planning.",
                dangerous=False,
                rollback=None,
                docs_url=VHD_NATIVE_BOOT_DOCS_URL,
                prerequisites=["Step deploy-stage-boot-files completed"],
                expected_result="Placeholder chain integrity checks pass",
                rollback_action="n/a",
                verification_action="Inspect expected staged files",
                risk_level="medium",
            ),
        ]
        return OperationPlan(
            title="Deployment Preparation Plan",
            target_platform="Cross-platform planning",
            steps=steps,
            warnings=[
                "Real Linux deployment into VHD/VHDX is still placeholder.",
            ],
            dangerous=False,
            requires_admin=False,
            experimental=True,
        )


@dataclass(slots=True)
class FullInstallPlanner:
    """Composes all planner layers into a single install plan."""

    vhd_planner: VhdOperationPlanner
    bcd_planner: BcdOperationPlanner
    deployment_planner: DeploymentOperationPlanner

    @classmethod
    def from_defaults(cls, command_builder: BcdCommandBuilder) -> FullInstallPlanner:
        return cls(
            vhd_planner=VhdOperationPlanner(),
            bcd_planner=BcdOperationPlanner(command_builder),
            deployment_planner=DeploymentOperationPlanner(),
        )

    def build(
        self,
        *,
        iso_path: Path,
        vhd_spec: VhdSpec,
        dry_run: bool,
        bcd_backup_path: Path,
    ) -> OperationPlan:
        deployment = self.deployment_planner.build(iso_path=iso_path, vhd_spec=vhd_spec)

        device = f"vhd=[<windows-volume>]\\{vhd_spec.path.name}"
        bcd = self.bcd_planner.build(
            description="Linux VHD Launcher",
            device=device,
            loader_path=r"\EFI\BOOT\BOOTX64.EFI",
            backup_path=bcd_backup_path,
        )
        vhd = self.vhd_planner.build(vhd_spec)

        all_steps = deployment.steps + vhd.steps + bcd.steps
        warnings = [
            "Dry-run mode prints and validates plan only."
            if dry_run
            else "Execution mode requires guarded safety flags.",
            *deployment.warnings,
            *vhd.warnings,
            *bcd.warnings,
        ]

        return OperationPlan(
            title="Full Install Plan",
            target_platform="Windows (execution), Cross-platform (dry-run planning)",
            steps=all_steps,
            warnings=warnings,
            dangerous=True,
            requires_admin=True,
            experimental=True,
        )


def build_windows_lab_plan() -> OperationPlan:
    """Builds manual Windows VM validation plan without performing operations."""

    steps = [
        PlannedStep(
            id="lab-snapshot",
            title="Prepare clean VM snapshot",
            command_preview=None,
            description="Create revertable snapshot before any boot configuration change.",
            dangerous=False,
            rollback="Revert VM to snapshot.",
            docs_url=None,
            prerequisites=["Disposable VM only"],
            expected_result="Snapshot created and named",
            rollback_action="Restore snapshot",
            verification_action="Confirm snapshot metadata in hypervisor",
            risk_level="low",
        ),
        PlannedStep(
            id="lab-admin-check",
            title="Verify administrator session",
            command_preview=["whoami", "/groups"],
            description="Ensure elevated admin token is active on Windows VM.",
            dangerous=False,
            rollback=None,
            docs_url=None,
            prerequisites=["VM is booted"],
            expected_result="Admin token available",
            rollback_action="n/a",
            verification_action="Check admin group in output",
            risk_level="low",
        ),
        PlannedStep(
            id="lab-secure-boot",
            title="Check Secure Boot state",
            command_preview=["powershell", "-NoProfile", "Confirm-SecureBootUEFI"],
            description="Record Secure Boot on/off state before test run.",
            dangerous=False,
            rollback=None,
            docs_url=None,
            prerequisites=["PowerShell available"],
            expected_result="Secure Boot state captured",
            rollback_action="n/a",
            verification_action="Persist command output in report",
            risk_level="low",
        ),
        PlannedStep(
            id="lab-bitlocker",
            title="Check BitLocker state",
            command_preview=["manage-bde", "-status"],
            description="Record BitLocker status for system and test volumes.",
            dangerous=False,
            rollback=None,
            docs_url=None,
            prerequisites=["Admin session"],
            expected_result="BitLocker status captured",
            rollback_action="n/a",
            verification_action="Persist output in report",
            risk_level="medium",
        ),
        PlannedStep(
            id="lab-create-vhdx",
            title="Create test VHDX",
            command_preview=["diskpart", "/s", "<generated-script>"],
            description="Create temporary test VHDX only inside VM.",
            dangerous=True,
            rollback="Delete temporary VHDX.",
            docs_url=VIRTDISK_DOCS_URL,
            prerequisites=["Snapshot exists", "Lab directory prepared"],
            expected_result="Temporary VHDX file is created",
            rollback_action="Detach and delete VHDX",
            verification_action="Check file cleanup after smoke",
            risk_level="high",
        ),
        PlannedStep(
            id="lab-attach-detach",
            title="Attach then detach test VHDX",
            command_preview=["diskpart", "/s", "<generated-script>"],
            description="Verify attach/detach flow is stable in VM environment.",
            dangerous=True,
            rollback="Detach VHDX if still attached.",
            docs_url=VIRTDISK_DOCS_URL,
            prerequisites=["Step lab-create-vhdx completed"],
            expected_result="Attach/detach succeeds",
            rollback_action="Detach VHDX",
            verification_action="Confirm VHDX no longer attached",
            risk_level="high",
        ),
        PlannedStep(
            id="lab-export-bcd",
            title="Export BCD backup",
            command_preview=["bcdedit", "/export", "<backup-path>"],
            description="Create BCD backup before any entry creation.",
            dangerous=False,
            rollback="Restore BCD from backup if needed.",
            docs_url=BCD_DOCS_URL,
            prerequisites=["Admin session", "Snapshot exists"],
            expected_result="BCD backup file exists",
            rollback_action="bcdedit /import <backup-path>",
            verification_action="Verify backup file hash",
            risk_level="medium",
        ),
        PlannedStep(
            id="lab-experimental-entry",
            title="Create experimental entry only with explicit unsafe flags",
            command_preview=[
                "linux-vhd-launcher",
                "install",
                "--execute-real-windows-ops",
                "--i-understand-this-is-experimental",
            ],
            description="Run guarded experimental path only after explicit opt-in.",
            dangerous=True,
            rollback="Delete entry and restore BCD backup.",
            docs_url=ADD_BOOT_ENTRY_DOCS_URL,
            prerequisites=["Steps lab-export-bcd and lab-attach-detach completed"],
            expected_result="Temporary test entry GUID recorded",
            rollback_action="Delete test GUID and restore backup",
            verification_action="Ensure entry is absent after rollback",
            risk_level="critical",
        ),
        PlannedStep(
            id="lab-rollback-check",
            title="Verify rollback and cleanup",
            command_preview=None,
            description="Confirm created entry can be deleted and VM returns to baseline.",
            dangerous=True,
            rollback="Revert snapshot if verification fails.",
            docs_url=BCD_DOCS_URL,
            prerequisites=["Step lab-experimental-entry completed"],
            expected_result="No temporary BCD entries remain",
            rollback_action="Restore VM snapshot",
            verification_action="Run bcdedit /enum all and compare to baseline",
            risk_level="critical",
        ),
    ]

    return OperationPlan(
        title="Windows VM Lab Validation Plan",
        target_platform="Windows VM only",
        steps=steps,
        warnings=[
            "No steps are executed by this command; this is a manual validation checklist.",
            "Experimental Linux boot chain must be tested only in disposable VM snapshots.",
        ],
        dangerous=True,
        requires_admin=True,
        experimental=True,
    )
