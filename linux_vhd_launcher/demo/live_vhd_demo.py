"""Orchestration for v0.6-demo live ISO VHD payload workflow."""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from linux_vhd_launcher.errors import UnsafeRealOperationError
from linux_vhd_launcher.models import LiveIsoInfo, LiveVhdBuildPlan, LiveVhdLayout, OperationPlan
from linux_vhd_launcher.services.live_boot_registration import (
    LiveRegistrationOutcome,
    LiveRegistrationRequest,
    choose_registration_strategy,
)
from linux_vhd_launcher.services.live_payload import (
    LiveVhdBuildOutcome,
    build_live_vhd,
    build_live_vhd_layout,
    build_live_vhd_plan,
    inspect_live_iso,
)
from linux_vhd_launcher.system.windows_privileges import is_admin, is_windows_platform

FINAL_DEMO_STATUS = Literal[
    "planned",
    "payload_built",
    "registration_blocked",
    "registration_experimental_done",
    "registration_experimental_done_but_boot_failed",
    "registration_failed",
    "bootability_unverified",
    "bootability_confirmed_manual",
]


@dataclass(slots=True)
class DemoContext:
    """Shared command context for live demo operations."""

    lab_dir: Path
    report_dir: Path
    dry_run: bool
    execute_real_windows_ops: bool
    confirmation_token: bool
    confirm_vm_snapshot: bool
    allow_known_failed_strategy: bool = False
    allow_esp_write: bool = False
    allow_firmware_entry: bool = False
    allow_secure_boot_experiment: bool = False
    allow_unprobed_bootapp_vhd: bool = False


@dataclass(slots=True)
class DemoExecutionResult:
    """High-level command output payload."""

    status: str
    iso: LiveIsoInfo | None = None
    layout: LiveVhdLayout | None = None
    plan: LiveVhdBuildPlan | None = None
    build: LiveVhdBuildOutcome | None = None
    registration: LiveRegistrationOutcome | None = None
    warnings: list[str] | None = None
    blockers: list[str] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "iso": self.iso.to_dict() if self.iso is not None else None,
            "layout": self.layout.to_dict() if self.layout is not None else None,
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "build": self.build.to_dict() if self.build is not None else None,
            "registration": self.registration.to_dict() if self.registration is not None else None,
            "warnings": self.warnings or [],
            "blockers": self.blockers or [],
        }


def inspect_iso(*, iso_path: Path) -> DemoExecutionResult:
    """Inspect ISO and persist info artifact."""
    iso_info = inspect_live_iso(iso_path)
    return DemoExecutionResult(status="planned", iso=iso_info)


def plan_live(
    *,
    iso_path: Path,
    vhd_path: Path,
    size_gb: int,
) -> DemoExecutionResult:
    """Build dry-run live payload plan."""
    iso_info = inspect_live_iso(iso_path)
    layout = build_live_vhd_layout(
        iso_info=iso_info,
        vhd_path=vhd_path,
        size_gb=size_gb,
        format="vhdx" if vhd_path.suffix.lower() == ".vhdx" else "vhd",
    )
    plan = build_live_vhd_plan(iso=iso_info, layout=layout)
    return DemoExecutionResult(
        status="planned",
        iso=iso_info,
        layout=layout,
        plan=plan,
        warnings=plan.warnings,
        blockers=plan.blockers,
    )


def build_payload(
    *,
    context: DemoContext,
    iso_path: Path,
    vhd_path: Path,
    size_gb: int,
) -> DemoExecutionResult:
    """Build VHD payload with full safety gate enforcement."""
    _ensure_paths(context)
    iso_info = inspect_live_iso(iso_path)
    layout = build_live_vhd_layout(
        iso_info=iso_info,
        vhd_path=vhd_path,
        size_gb=size_gb,
        format="vhdx" if vhd_path.suffix.lower() == ".vhdx" else "vhd",
    )

    plan = build_live_vhd_plan(iso=iso_info, layout=layout)
    _write_demo_artifacts(context.report_dir, iso=iso_info, layout=layout, plan=plan)

    if not context.dry_run:
        _enforce_real_gate(context)

    build = build_live_vhd(
        iso=iso_info,
        layout=layout,
        lab_dir=context.lab_dir,
        report_dir=context.report_dir,
        dry_run=context.dry_run,
        execute_real_windows_ops=context.execute_real_windows_ops,
        confirmation_token=context.confirmation_token,
        confirm_vm_snapshot=context.confirm_vm_snapshot,
    )

    (context.report_dir / "live_build_outcome.json").write_text(
        json.dumps(build.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )

    status = build.status
    _write_demo_status(
        context.report_dir,
        status=status,
        notes=["bootability_unverified: manual reboot not tested yet"],
    )

    return DemoExecutionResult(
        status=status,
        iso=iso_info,
        layout=layout,
        plan=plan,
        build=build,
        warnings=plan.warnings,
        blockers=plan.blockers,
    )


def register_live(
    *,
    context: DemoContext,
    vhd_path: Path,
    strategy: str,
) -> DemoExecutionResult:
    """Run registration strategy and persist artifacts."""
    if not context.report_dir.exists() or not context.report_dir.is_dir():
        raise UnsafeRealOperationError("register-bcd requires existing --report-dir directory.")
    if not context.lab_dir.exists() or not context.lab_dir.is_dir():
        raise UnsafeRealOperationError("register-bcd requires existing --lab-dir directory.")

    layout = LiveVhdLayout(
        vhd_path=vhd_path,
        format="vhdx" if vhd_path.suffix.lower() == ".vhdx" else "vhd",
        size_gb=0,
        efi_partition_size_mb=512,
        data_partition_fs="ntfs",
        iso_inside_path="/live/unknown.iso",
        efi_loader_path="/EFI/BOOT/BOOTX64.EFI",
        grub_cfg_path="/EFI/BOOT/grub.cfg",
    )

    selected = choose_registration_strategy(strategy)
    outcome = selected.register(
        LiveRegistrationRequest(
            layout=layout,
            report_dir=context.report_dir,
            lab_dir=context.lab_dir,
            dry_run=context.dry_run,
            execute_real_windows_ops=context.execute_real_windows_ops,
            confirmation_token=context.confirmation_token,
            confirm_vm_snapshot=context.confirm_vm_snapshot,
            allow_known_failed_strategy=context.allow_known_failed_strategy,
            allow_esp_write=context.allow_esp_write,
            allow_firmware_entry=context.allow_firmware_entry,
            allow_secure_boot_experiment=context.allow_secure_boot_experiment,
            allow_unprobed_bootapp_vhd=context.allow_unprobed_bootapp_vhd,
        )
    )

    _write_registration_artifacts(context.report_dir, outcome)
    _write_bcd_diff_if_present(context.report_dir)

    if outcome.status == "registration_experimental_done":
        _write_demo_status(
            context.report_dir,
            status="bootability_unverified",
            notes=["registration_experimental_done", "Manual reboot test required."],
        )
    elif outcome.status == "registration_experimental_done_but_boot_failed":
        known_failed = outcome.known_failed_strategy or "unknown"
        _write_demo_status(
            context.report_dir,
            status="registration_experimental_done_but_boot_failed",
            notes=[
                f"known_failed_strategy: {known_failed}",
                "bootability_unverified",
            ],
        )
    elif outcome.status == "registration_failed":
        _write_demo_status(
            context.report_dir,
            status="bootability_unverified",
            notes=["registration_failed"] + outcome.blockers,
        )
    elif outcome.status == "registration_blocked":
        _write_demo_status(
            context.report_dir,
            status="registration_blocked",
            notes=outcome.blockers,
        )

    return DemoExecutionResult(
        status=outcome.status,
        layout=layout,
        registration=outcome,
        warnings=outcome.warnings,
        blockers=outcome.blockers,
    )


def unregister_live_bcd(
    *,
    context: DemoContext,
    guid: str,
) -> DemoExecutionResult:
    """Delete experimental BCD entry by GUID using full real-operation gate."""
    if not context.report_dir.exists() or not context.report_dir.is_dir():
        raise UnsafeRealOperationError("unregister-bcd requires existing --report-dir directory.")

    command = ["bcdedit", "/delete", guid, "/f"]
    if context.dry_run:
        dry_payload = {
            "status": "planned",
            "command": command,
            "notes": ["Dry-run only."],
        }
        (context.report_dir / "live_unregistration_outcome.json").write_text(
            json.dumps(dry_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return DemoExecutionResult(status="planned", warnings=["Dry-run: no BCD mutation executed."])

    _enforce_real_gate(context)
    if not is_windows_platform():
        raise UnsafeRealOperationError("Real unregister requires Windows host.")

    from linux_vhd_launcher.system.runner import CommandRunner

    runner = CommandRunner(dry_run=False)
    result = runner.run(command, elevated_required=True, check=True)
    payload: dict[str, object] = {
        "status": "registration_experimental_done",
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "rollback": "Use bcdedit /import <backup> only in explicit emergency mode.",
    }
    (context.report_dir / "live_unregistration_outcome.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_demo_status(
        context.report_dir,
        status="bootability_unverified",
        notes=["experimental BCD entry removed"],
    )
    return DemoExecutionResult(status="registration_experimental_done")


def stage_esp_plan(
    *,
    context: DemoContext,
    vhd_path: Path,
) -> DemoExecutionResult:
    """Generate dry-run ESP staging plan via firmware-efi-staged strategy."""
    plan_context = DemoContext(
        lab_dir=context.lab_dir,
        report_dir=context.report_dir,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
        allow_known_failed_strategy=False,
        allow_esp_write=False,
        allow_firmware_entry=False,
        allow_secure_boot_experiment=False,
        allow_unprobed_bootapp_vhd=False,
    )
    return register_live(
        context=plan_context,
        vhd_path=vhd_path,
        strategy="firmware-efi-staged",
    )


def stage_esp_apply(
    *,
    context: DemoContext,
    vhd_path: Path,
) -> DemoExecutionResult:
    """Attempt ESP staging strategy (currently blocked in real mode)."""
    return register_live(
        context=context,
        vhd_path=vhd_path,
        strategy="firmware-efi-staged",
    )


def stage_esp_cleanup(
    *,
    context: DemoContext,
) -> DemoExecutionResult:
    """Emit cleanup plan for staged ESP files and optional firmware entry."""
    commands = [
        "bcdedit /delete {GUID} /f  # if created",
        "mountvol S: /s",
        "Remove-Item -Recurse -Force S:\\EFI\\LinuxVHDLauncher\\ubuntu-live",
        "mountvol S: /d",
    ]
    payload = {
        "status": "planned",
        "commands": commands,
        "notes": [
            "Cleanup plan only. Execute manually in disposable VM.",
            "If BCD/firmware entry was never created, skip delete command.",
        ],
    }
    context.report_dir.mkdir(parents=True, exist_ok=True)
    (context.report_dir / "esp_cleanup_plan.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return DemoExecutionResult(status="planned", warnings=list(payload["notes"]))


def install_live(
    *,
    context: DemoContext,
    iso_path: Path,
    vhd_path: Path,
    size_gb: int,
    strategy: str,
) -> DemoExecutionResult:
    """Combined build + registration flow."""
    build_result = build_payload(
        context=context,
        iso_path=iso_path,
        vhd_path=vhd_path,
        size_gb=size_gb,
    )
    registration_result = register_live(
        context=context,
        vhd_path=vhd_path,
        strategy=strategy,
    )

    status = registration_result.status
    return DemoExecutionResult(
        status=status,
        iso=build_result.iso,
        layout=build_result.layout,
        plan=build_result.plan,
        build=build_result.build,
        registration=registration_result.registration,
        warnings=(build_result.warnings or []) + (registration_result.warnings or []),
        blockers=registration_result.blockers,
    )


def uninstall_live(
    *,
    context: DemoContext,
    guid: str,
    delete_vhd: bool,
    vhd_path: Path | None,
) -> DemoExecutionResult:
    """Remove only known temporary registration artifacts."""
    manifest_path = context.report_dir / "live_registration_manifest.json"
    if not manifest_path.exists():
        raise UnsafeRealOperationError("No registration manifest found. Refusing uninstall.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    known_guid = str(manifest.get("guid", ""))
    if not known_guid or known_guid.lower() != guid.lower():
        raise UnsafeRealOperationError("Refusing uninstall for unknown GUID.")

    if not context.dry_run:
        _enforce_real_gate(context)
        if not is_windows_platform():
            raise UnsafeRealOperationError("Real uninstall requires Windows host.")

        from linux_vhd_launcher.system.runner import CommandRunner

        runner = CommandRunner(dry_run=False)
        runner.run(["bcdedit", "/delete", guid, "/f"], elevated_required=True, check=True)

    if delete_vhd:
        target = vhd_path if vhd_path is not None else Path(str(manifest.get("vhd", "")))
        if not str(target):
            raise UnsafeRealOperationError("--delete-vhd requested but VHD path is unavailable.")
        if not context.dry_run and target.exists():
            target.unlink(missing_ok=True)

    _write_demo_status(context.report_dir, status="bootability_unverified", notes=["demo entry removed"])
    return DemoExecutionResult(status="planned")


def mark_boot_result(
    *,
    report_dir: Path,
    result: Literal["booted", "failed", "not-tested"],
    notes: str,
) -> DemoExecutionResult:
    """Persist manual reboot evidence after VM test."""
    normalized = "bootability_unverified"
    if result == "booted":
        normalized = "bootability_confirmed_manual"

    payload = {
        "result": result,
        "notes": notes,
    }
    (report_dir / "manual_boot_result.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_demo_status(report_dir, status=normalized, notes=[notes])
    return DemoExecutionResult(status=normalized)


def _write_demo_artifacts(
    report_dir: Path,
    *,
    iso: LiveIsoInfo,
    layout: LiveVhdLayout,
    plan: LiveVhdBuildPlan,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    operation_plan = OperationPlan(
        title="Live VHD Demo Plan",
        target_platform="Windows VM",
        steps=plan.steps,
        warnings=plan.warnings + plan.blockers,
        dangerous=True,
        requires_admin=True,
        experimental=True,
    )
    (report_dir / "OperationPlan.json").write_text(
        json.dumps(operation_plan.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "LiveIsoInfo.json").write_text(
        json.dumps(iso.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "LiveVhdLayout.json").write_text(
        json.dumps(layout.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "LiveVhdBuildPlan.json").write_text(
        json.dumps(plan.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )


def _write_registration_artifacts(report_dir: Path, outcome: LiveRegistrationOutcome) -> None:
    (report_dir / "live_registration_outcome.json").write_text(
        json.dumps(outcome.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )


def _write_bcd_diff_if_present(report_dir: Path) -> None:
    before = report_dir / "bcd_baseline_before.txt"
    after = report_dir / "bcd_baseline_after.txt"
    if not before.exists() or not after.exists():
        return

    diff = difflib.unified_diff(
        before.read_text(encoding="utf-8", errors="replace").splitlines(),
        after.read_text(encoding="utf-8", errors="replace").splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    (report_dir / "bcd_baseline_diff.txt").write_text("\n".join(diff) + "\n", encoding="utf-8")


def _write_demo_status(report_dir: Path, *, status: str, notes: list[str]) -> None:
    payload = {
        "status": status,
        "notes": notes,
    }
    (report_dir / "demo_status.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _ensure_paths(context: DemoContext) -> None:
    context.lab_dir.mkdir(parents=True, exist_ok=True)
    context.report_dir.mkdir(parents=True, exist_ok=True)


def _enforce_real_gate(context: DemoContext) -> None:
    if not context.execute_real_windows_ops:
        raise UnsafeRealOperationError("Real operations require --execute-real-windows-ops")
    if not context.confirmation_token:
        raise UnsafeRealOperationError("Real operations require --i-understand-this-is-experimental")
    if not context.confirm_vm_snapshot:
        raise UnsafeRealOperationError("Real operations require --confirm-vm-snapshot")
    if not is_windows_platform():
        raise UnsafeRealOperationError("Real operations are allowed only on Windows")
    if not is_admin():
        raise UnsafeRealOperationError("Real operations require administrator rights")
