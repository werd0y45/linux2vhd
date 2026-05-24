"""CLI entrypoint for LinuxVHDLauncher."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from linux_vhd_launcher.capabilities import run_capability_scanners
from linux_vhd_launcher.config import ConfigManager, RegistryStore
from linux_vhd_launcher.demo.live_vhd_demo import (
    DemoContext,
    build_payload,
    install_live,
    mark_boot_result,
    plan_live,
    register_live,
    uninstall_live,
)
from linux_vhd_launcher.demo.live_vhd_demo import (
    inspect_iso as demo_inspect_iso,
)
from linux_vhd_launcher.errors import (
    LinuxVhdLauncherError,
    RegistryFormatError,
    UnsafeRealOperationError,
    UnsupportedPlatformError,
    ValidationReportFormatError,
)
from linux_vhd_launcher.logging_setup import setup_logging
from linux_vhd_launcher.models import (
    BackendCapability,
    CampaignEnvironment,
    DoctorReport,
    ProbeResult,
    RollbackEvidence,
    RollbackStatus,
    ValidationArtifact,
    VhdSpec,
    VmRunnerConfig,
)
from linux_vhd_launcher.services.boot_manager import BootManager, RegistryUpdater
from linux_vhd_launcher.services.installer_service import (
    FakeDeploymentBackend,
    InstallerService,
    InstallRequest,
)
from linux_vhd_launcher.services.iso_manager import ISOManager
from linux_vhd_launcher.services.operation_planners import build_windows_lab_plan
from linux_vhd_launcher.services.secure_boot_helper import SecureBootHelper
from linux_vhd_launcher.services.vhd_manager import VHDManager
from linux_vhd_launcher.system.runner import CommandRunner
from linux_vhd_launcher.system.windows_bcd import (
    BcdCommandBuilder,
    create_dry_run_bcd_backend,
    create_windows_bcd_backend,
)
from linux_vhd_launcher.system.windows_privileges import is_admin, is_windows_platform
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate
from linux_vhd_launcher.system.windows_vhd import (
    DiskPartVhdBackend,
    FakeVhdBackend,
    VhdBackend,
    VirtualDiskApiBackend,
)
from linux_vhd_launcher.validation import (
    BundleOptions,
    StepExecutionError,
    StepExecutionResult,
    add_or_replace_artifact,
    collect_artifacts,
    compute_sha256,
    create_artifact_bundle,
    create_initial_report,
    create_report_directory,
    load_report,
    record_step,
    render_markdown,
    report_path,
    run_dry_campaign,
    save_report,
)
from linux_vhd_launcher.vm_runners import VmRunner, build_vm_runner


def _base_dir() -> Path:
    env = os.getenv("LINUX_VHD_LAUNCHER_HOME")
    if env:
        return Path(env)
    return Path.cwd() / ".linux_vhd_launcher"


def _default_config_file() -> Path:
    return _base_dir() / "config.json"


def _package_default_config() -> Path:
    return Path(__file__).parent / "data" / "default_config.json"


def _default_backup_path(config_backup_dir: Path) -> Path:
    return config_backup_dir / "bcd_manual_backup.bcd"


def build_installer(
    *,
    dry_run: bool,
    execute_real_windows_ops: bool,
    confirmation_token: bool,
    backup_path: Path | None,
    allowed_lab_dir: Path | None = None,
    validation_report_path: Path | None = None,
) -> tuple[InstallerService, RegistryStore]:
    """Create the service graph for CLI or GUI."""
    config = ConfigManager(_default_config_file(), _package_default_config()).load_or_create()
    setup_logging(config.log_level)

    runner = CommandRunner(dry_run=dry_run)
    effective_backup = (
        backup_path
        if backup_path is not None
        else _default_backup_path(config.bcd_backup_dir)
    )
    gate = RealWindowsOpsGate(
        execute_real_windows_ops=execute_real_windows_ops,
        confirmation_token=confirmation_token,
        dry_run=dry_run,
        backup_path=effective_backup,
        allowed_lab_dir=allowed_lab_dir,
        validation_report_path=validation_report_path,
    )

    vhd_backend: VhdBackend
    if dry_run:
        bcd_backend = create_dry_run_bcd_backend(runner)
        vhd_backend = FakeVhdBackend(free_space_bytes=10_000 * 1024**3)
    else:
        bcd_backend = create_windows_bcd_backend(runner, gate=gate)
        vhd_backend = DiskPartVhdBackend(runner, gate=gate)

    registry = RegistryStore(config.registry_path)
    installer = InstallerService(
        iso_manager=ISOManager(config.catalog_path),
        vhd_manager=VHDManager(vhd_backend),
        boot_manager=BootManager(
            backend=bcd_backend,
            command_builder=BcdCommandBuilder(),
            registry_updater=RegistryUpdater(registry),
        ),
        secure_boot_helper=SecureBootHelper(),
        deployment_backend=FakeDeploymentBackend(),
    )
    return installer, registry


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="linux-vhd-launcher")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Show environment diagnostics")
    doctor.add_argument("--json", action="store_true", help="Alias for --format json")
    doctor.add_argument("--format", choices=["text", "json"], default="text")

    scan = sub.add_parser("scan-iso", help="Scan directory for ISO files")
    scan.add_argument("directory", type=Path)

    plan = sub.add_parser("plan-install", help="Validate and print install plan")
    plan.add_argument("--iso", type=Path, required=True)
    plan.add_argument("--vhd", type=Path, required=True)
    plan.add_argument("--size-gb", type=int, required=True)
    plan.add_argument("--format", choices=["vhd", "vhdx"], required=True)
    plan.add_argument("--dry-run", action="store_true")
    plan.add_argument("--json", action="store_true", help="Alias for --output-format json")
    plan.add_argument("--output-format", choices=["text", "json"], default="text")

    plan_lab = sub.add_parser("plan-windows-lab", help="Print manual Windows VM validation plan")
    plan_lab.add_argument("--json", action="store_true", help="Alias for --output-format json")
    plan_lab.add_argument("--output-format", choices=["text", "json"], default="text")

    install = sub.add_parser("install", help="Execute installation workflow")
    install.add_argument("--iso", type=Path, required=True)
    install.add_argument("--vhd", type=Path, required=True)
    install.add_argument("--size-gb", type=int, required=True)
    install.add_argument("--format", choices=["vhd", "vhdx"], required=True)
    install.add_argument("--description", default="Linux VHD Launcher")
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--execute-real-windows-ops", action="store_true")
    install.add_argument("--i-understand-this-is-experimental", action="store_true")
    install.add_argument("--bcd-backup-path", type=Path)

    uninstall = sub.add_parser("uninstall", help="Delete BCD entry and registry item")
    uninstall.add_argument("--guid", required=True)
    uninstall.add_argument("--vhd", type=Path, required=True)
    uninstall.add_argument("--dry-run", action="store_true")
    uninstall.add_argument("--execute-real-windows-ops", action="store_true")
    uninstall.add_argument("--i-understand-this-is-experimental", action="store_true")
    uninstall.add_argument("--bcd-backup-path", type=Path)

    sub.add_parser("show-registry", help="Print local registry entries")

    validation = sub.add_parser("validation", help="Validation campaign commands")
    validation_sub = validation.add_subparsers(dest="validation_command", required=True)

    validation_init = validation_sub.add_parser(
        "init", help="Initialize machine-readable validation report directory"
    )
    validation_init.add_argument("--report-dir", type=Path)
    validation_init.add_argument("--vm-snapshot-name")

    validation_run_dry = validation_sub.add_parser(
        "run-dry", help="Run Linux-safe dry validation campaign"
    )
    validation_run_dry.add_argument("--report-dir", type=Path, required=True)

    validation_collect = validation_sub.add_parser(
        "collect", help="Collect report artifacts and hashes"
    )
    validation_collect.add_argument("--report-dir", type=Path, required=True)

    validation_capabilities = validation_sub.add_parser(
        "capabilities", help="Run non-destructive backend capability scan"
    )
    validation_capabilities.add_argument("--report-dir", type=Path)
    validation_capabilities.add_argument("--json", action="store_true")

    validation_render = validation_sub.add_parser(
        "render", help="Render markdown report from report.json"
    )
    validation_render.add_argument("--report-dir", type=Path, required=True)

    validation_status = validation_sub.add_parser(
        "status", help="Print short validation summary"
    )
    validation_status.add_argument("--report-dir", type=Path, required=True)

    validation_probe = validation_sub.add_parser(
        "windows-probe", help="Guarded Windows probe checks"
    )
    validation_probe.add_argument("--report-dir", type=Path, required=True)
    validation_probe.add_argument("--execute-real-windows-ops", action="store_true")
    validation_probe.add_argument("--i-understand-this-is-experimental", action="store_true")
    validation_probe.add_argument("--no-dry-run", action="store_true")

    validation_vhd_smoke = validation_sub.add_parser(
        "windows-vhd-smoke", help="Guarded VHD create/attach/detach smoke in test directory"
    )
    validation_vhd_smoke.add_argument("--report-dir", type=Path, required=True)
    validation_vhd_smoke.add_argument("--execute-real-windows-ops", action="store_true")
    validation_vhd_smoke.add_argument("--i-understand-this-is-experimental", action="store_true")
    validation_vhd_smoke.add_argument("--no-dry-run", action="store_true")
    validation_vhd_smoke.add_argument("--backend", choices=["virtdisk", "diskpart"], default="virtdisk")

    validation_bcd_backup = validation_sub.add_parser(
        "windows-bcd-backup-smoke", help="Guarded BCD export-only smoke"
    )
    validation_bcd_backup.add_argument("--report-dir", type=Path, required=True)
    validation_bcd_backup.add_argument("--execute-real-windows-ops", action="store_true")
    validation_bcd_backup.add_argument("--i-understand-this-is-experimental", action="store_true")
    validation_bcd_backup.add_argument("--no-dry-run", action="store_true")

    validation_bcd_mutation = validation_sub.add_parser(
        "windows-bcd-mutation-smoke",
        help="Guarded temporary BCD entry create/delete experiment with rollback verification",
    )
    validation_bcd_mutation.add_argument("--report-dir", type=Path, required=True)
    validation_bcd_mutation.add_argument("--lab-dir", type=Path, required=True)
    validation_bcd_mutation.add_argument("--execute-real-windows-ops", action="store_true")
    validation_bcd_mutation.add_argument("--i-understand-this-is-experimental", action="store_true")
    validation_bcd_mutation.add_argument("--no-dry-run", action="store_true")
    validation_bcd_mutation.add_argument("--confirm-vm-snapshot", action="store_true")
    validation_bcd_mutation.add_argument("--include-displayorder-experiment", action="store_true")

    validation_vm_status = validation_sub.add_parser(
        "vm-status", help="Check VM runner readiness for campaign"
    )
    validation_vm_status.add_argument("--runner", choices=["manual", "hyperv", "external"], default="manual")
    validation_vm_status.add_argument("--vm-name")
    validation_vm_status.add_argument("--snapshot-name")
    validation_vm_status.add_argument("--report-dir", type=Path)
    validation_vm_status.add_argument("--confirm-vm-snapshot", action="store_true")
    validation_vm_status.add_argument("--allow-mutation", action="store_true")

    validation_run_campaign = validation_sub.add_parser(
        "run-campaign", help="Orchestrate validation campaign flow"
    )
    validation_run_campaign.add_argument("--report-dir", type=Path, required=True)
    validation_run_campaign.add_argument("--runner", choices=["manual", "hyperv", "external"], default="manual")
    validation_run_campaign.add_argument("--vm-name")
    validation_run_campaign.add_argument("--snapshot-name")
    validation_run_campaign.add_argument("--confirm-vm-snapshot", action="store_true")
    validation_run_campaign.add_argument("--allow-mutation", action="store_true")
    validation_run_campaign.add_argument("--include-windows-probe", action="store_true")
    validation_run_campaign.add_argument("--include-windows-vhd-smoke", action="store_true")
    validation_run_campaign.add_argument("--include-windows-bcd-backup-smoke", action="store_true")
    validation_run_campaign.add_argument("--include-windows-bcd-mutation-smoke", action="store_true")
    validation_run_campaign.add_argument("--execute-real-windows-ops", action="store_true")
    validation_run_campaign.add_argument("--i-understand-this-is-experimental", action="store_true")
    validation_run_campaign.add_argument("--no-dry-run", action="store_true")
    validation_run_campaign.add_argument("--lab-dir", type=Path)
    validation_run_campaign.add_argument("--include-displayorder-experiment", action="store_true")

    validation_bundle = validation_sub.add_parser(
        "bundle", help="Create portable artifact bundle (zip or tar.gz)"
    )
    validation_bundle.add_argument("--report-dir", type=Path, required=True)
    validation_bundle.add_argument("--redact", action="store_true")
    validation_bundle.add_argument("--format", choices=["zip", "targz"], default="zip")

    demo = sub.add_parser("demo", help="Live ISO VHD demo workflow commands")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)

    demo_inspect = demo_sub.add_parser("inspect-iso", help="Inspect live ISO layout")
    demo_inspect.add_argument("--iso", type=Path, required=True)
    demo_inspect.add_argument("--json", action="store_true")

    demo_live = demo_sub.add_parser("live", help="Live VHD payload demo operations")
    demo_live_sub = demo_live.add_subparsers(dest="demo_live_command", required=True)

    demo_live_plan = demo_live_sub.add_parser("plan", help="Plan live VHD payload build")
    demo_live_plan.add_argument("--iso", type=Path, required=True)
    demo_live_plan.add_argument("--vhd", type=Path, required=True)
    demo_live_plan.add_argument("--size-gb", type=int, required=True)
    demo_live_plan.add_argument("--lab-dir", type=Path, required=True)
    demo_live_plan.add_argument("--json", action="store_true")

    demo_live_build = demo_live_sub.add_parser("build-vhd", help="Build live ISO payload in VHD")
    demo_live_build.add_argument("--iso", type=Path, required=True)
    demo_live_build.add_argument("--vhd", type=Path, required=True)
    demo_live_build.add_argument("--size-gb", type=int, required=True)
    demo_live_build.add_argument("--lab-dir", type=Path, required=True)
    demo_live_build.add_argument("--report-dir", type=Path, required=True)
    demo_live_build.add_argument("--execute-real-windows-ops", action="store_true")
    demo_live_build.add_argument("--i-understand-this-is-experimental", action="store_true")
    demo_live_build.add_argument("--confirm-vm-snapshot", action="store_true")
    demo_live_build.add_argument("--no-dry-run", action="store_true")
    demo_live_build.add_argument("--json", action="store_true")

    demo_live_register = demo_live_sub.add_parser(
        "register-bcd", help="Register experimental boot entry for built VHD"
    )
    demo_live_register.add_argument("--vhd", type=Path, required=True)
    demo_live_register.add_argument("--lab-dir", type=Path, required=True)
    demo_live_register.add_argument("--report-dir", type=Path, required=True)
    demo_live_register.add_argument(
        "--strategy",
        choices=["auto", "bootmgr", "firmware", "blocked"],
        default="auto",
    )
    demo_live_register.add_argument("--execute-real-windows-ops", action="store_true")
    demo_live_register.add_argument("--i-understand-this-is-experimental", action="store_true")
    demo_live_register.add_argument("--confirm-vm-snapshot", action="store_true")
    demo_live_register.add_argument("--no-dry-run", action="store_true")
    demo_live_register.add_argument("--json", action="store_true")

    demo_live_install = demo_live_sub.add_parser(
        "install", help="Combined payload build and registration experiment"
    )
    demo_live_install.add_argument("--iso", type=Path, required=True)
    demo_live_install.add_argument("--vhd", type=Path, required=True)
    demo_live_install.add_argument("--size-gb", type=int, required=True)
    demo_live_install.add_argument("--lab-dir", type=Path, required=True)
    demo_live_install.add_argument("--report-dir", type=Path, required=True)
    demo_live_install.add_argument(
        "--strategy",
        choices=["auto", "bootmgr", "firmware", "blocked"],
        default="auto",
    )
    demo_live_install.add_argument("--execute-real-windows-ops", action="store_true")
    demo_live_install.add_argument("--i-understand-this-is-experimental", action="store_true")
    demo_live_install.add_argument("--confirm-vm-snapshot", action="store_true")
    demo_live_install.add_argument("--no-dry-run", action="store_true")
    demo_live_install.add_argument("--json", action="store_true")

    demo_live_uninstall = demo_live_sub.add_parser(
        "uninstall", help="Unregister temporary demo boot entry created by this app"
    )
    demo_live_uninstall.add_argument("--guid")
    demo_live_uninstall.add_argument("--vhd", type=Path)
    demo_live_uninstall.add_argument("--delete-vhd", action="store_true")
    demo_live_uninstall.add_argument("--lab-dir", type=Path, required=True)
    demo_live_uninstall.add_argument("--report-dir", type=Path, required=True)
    demo_live_uninstall.add_argument("--execute-real-windows-ops", action="store_true")
    demo_live_uninstall.add_argument("--i-understand-this-is-experimental", action="store_true")
    demo_live_uninstall.add_argument("--confirm-vm-snapshot", action="store_true")
    demo_live_uninstall.add_argument("--no-dry-run", action="store_true")
    demo_live_uninstall.add_argument("--json", action="store_true")

    demo_live_mark_boot = demo_live_sub.add_parser(
        "mark-boot-result", help="Record manual reboot test result"
    )
    demo_live_mark_boot.add_argument("--report-dir", type=Path, required=True)
    demo_live_mark_boot.add_argument(
        "--result",
        choices=["booted", "failed", "not-tested"],
        required=True,
    )
    demo_live_mark_boot.add_argument("--notes", default="")
    demo_live_mark_boot.add_argument("--json", action="store_true")
    return parser


def _spec_from_args(args: argparse.Namespace) -> VhdSpec:
    return VhdSpec(path=args.vhd, size_gb=args.size_gb, format=args.format)


def _render_operation_plan(plan: dict[str, object]) -> None:
    print(plan["title"])
    print(f"- target_platform: {plan['target_platform']}")
    print(f"- dangerous: {plan['dangerous']}")
    print(f"- requires_admin: {plan['requires_admin']}")
    print(f"- experimental: {plan['experimental']}")
    print("- warnings:")
    warnings_raw = plan.get("warnings")
    if isinstance(warnings_raw, list):
        for warning in warnings_raw:
            print(f"  - {warning}")
    print("- steps:")
    steps_raw = plan.get("steps")
    if isinstance(steps_raw, list):
        for step in steps_raw:
            if not isinstance(step, dict):
                continue
            command = step.get("command_preview")
            command_text = " ".join(command) if isinstance(command, list) else "<none>"
            print(f"  - [{step['id']}] {step['title']}")
            print(f"    dangerous={step['dangerous']} rollback={step['rollback']}")
            print(f"    risk_level={step.get('risk_level')}")
            print(f"    command={command_text}")
            print(f"    description={step['description']}")
            prerequisites = step.get("prerequisites")
            if isinstance(prerequisites, list) and prerequisites:
                print(f"    prerequisites={'; '.join(str(item) for item in prerequisites)}")
            if step.get("expected_result"):
                print(f"    expected_result={step['expected_result']}")
            if step.get("rollback_action"):
                print(f"    rollback_action={step['rollback_action']}")
            if step.get("verification_action"):
                print(f"    verification_action={step['verification_action']}")


def _doctor() -> dict[str, object]:
    pyqt6_available = True
    try:
        __import__("PyQt6")
    except Exception:
        pyqt6_available = False

    warnings_out: list[str] = []
    if not is_windows_platform():
        warnings_out.append(
            "Windows backend is unavailable on this host. Use dry-run and unit tests only."
        )

    return {
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "is_windows": is_windows_platform(),
        "is_admin": is_admin(),
        "pyqt6_available": pyqt6_available,
        "dry_run_available": True,
        "registry_path": str(_base_dir() / "vhd_registry.json"),
        "config_path": str(_default_config_file()),
        "warnings": warnings_out,
    }


def _doctor_report() -> DoctorReport:
    raw = _doctor()
    return DoctorReport.from_dict(raw)


def _campaign_environment() -> CampaignEnvironment:
    return CampaignEnvironment(
        machine_name=socket.gethostname(),
        os_version=platform.platform(),
        is_vm=None,
        hypervisor=None,
        secure_boot=None,
        bitlocker=None,
        is_admin=is_admin(),
        python_version=platform.python_version(),
    )


def _build_vm_runner_from_args(args: argparse.Namespace, *, report_dir: Path) -> VmRunner:
    require_snapshot = bool(
        getattr(args, "allow_mutation", False)
        or getattr(args, "include_windows_bcd_mutation_smoke", False)
    )
    config = VmRunnerConfig(
        runner=str(getattr(args, "runner", "manual")),  # type: ignore[arg-type]
        vm_name=str(getattr(args, "vm_name", "")) or None,
        snapshot_name=str(getattr(args, "snapshot_name", "")) or None,
        working_dir=report_dir,
        require_snapshot=require_snapshot,
        allow_mutation=bool(getattr(args, "allow_mutation", False)),
    )
    return build_vm_runner(
        config,
        snapshot_confirmed=bool(getattr(args, "confirm_vm_snapshot", False)),
        which=shutil.which,
    )


def _ensure_report_exists_or_init(report_dir: Path) -> ValidationArtifact | None:
    if report_path(report_dir).exists():
        return None
    doctor_payload = _doctor()
    doctor_report = DoctorReport.from_dict(doctor_payload)
    report_dir.mkdir(parents=True, exist_ok=True)
    campaign_id = f"campaign-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    (report_dir / "doctor_initial.json").write_text(
        json.dumps(doctor_payload, indent=2) + "\n",
        encoding="utf-8",
    )
    report = create_initial_report(
        report_dir=report_dir,
        host=doctor_report,
        campaign_id=campaign_id,
        vm_snapshot_name=None,
    )
    report.environment = _campaign_environment()
    save_report(report_dir, report)
    return ValidationArtifact(
        kind="report",
        path=report_path(report_dir),
        sha256=compute_sha256(report_path(report_dir)),
        description="Initialized report during run-campaign",
    )


def _report_dir_from_arg(path: Path | None) -> Path:
    if path is not None:
        return path
    return create_report_directory(Path.cwd())


def _registry_payload(registry: RegistryStore) -> list[dict[str, object]]:
    return [
        {
            "distro": item.distro,
            "vhd_path": str(item.vhd_path),
            "bcd_guid": item.bcd_guid,
            "created_at": item.created_at.isoformat(),
            "bcd_backup_path": str(item.bcd_backup_path) if item.bcd_backup_path else None,
        }
        for item in registry.list_items()
    ]


def _build_validation_gate(
    *,
    report_dir: Path,
    execute_real_windows_ops: bool,
    confirmation_token: bool,
    dry_run: bool,
    allowed_lab_dir: Path | None = None,
) -> RealWindowsOpsGate:
    backup_path = report_dir / "artifacts" / "bcd_backup_probe.bcd"
    return RealWindowsOpsGate(
        execute_real_windows_ops=execute_real_windows_ops,
        confirmation_token=confirmation_token,
        dry_run=dry_run,
        backup_path=backup_path,
        allowed_lab_dir=allowed_lab_dir if allowed_lab_dir is not None else report_dir,
        validation_report_path=report_path(report_dir),
    )


def _assert_windows_probe_allowed(gate: RealWindowsOpsGate) -> None:
    gate.assert_allowed(
        operation="validation windows-probe",
        rollback_plan="read-only probe",
        report_path=gate.validation_report_path,
        target_path=gate.allowed_lab_dir,
        require_rollback_plan=True,
        require_report=True,
        require_target_in_lab_dir=True,
    )


def _run_windows_probe(report_dir: Path, report: object, gate: RealWindowsOpsGate) -> dict[str, object]:
    del report
    _assert_windows_probe_allowed(gate)
    if not is_windows_platform():
        raise UnsupportedPlatformError("windows-probe can run only on Windows.")

    runner = CommandRunner(dry_run=False)
    powershell_available = shutil.which("powershell") is not None
    bcdedit_available = shutil.which("bcdedit") is not None
    bcdboot_available = shutil.which("bcdboot") is not None

    secure_boot: dict[str, object] = {"available": powershell_available}
    bitlocker: dict[str, object] = {"available": powershell_available}

    if powershell_available:
        secure_boot_cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Confirm-SecureBootUEFI",
        ]
        secure_boot_result = runner.run(secure_boot_cmd, elevated_required=False, check=False)
        secure_boot = {
            "available": True,
            "exit_code": secure_boot_result.returncode,
            "stdout": secure_boot_result.stdout.strip(),
            "stderr": secure_boot_result.stderr.strip(),
        }

        bitlocker_cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-BitLockerVolume | "
                "Select-Object MountPoint,ProtectionStatus,VolumeStatus | "
                "ConvertTo-Json -Compress"
            ),
        ]
        bitlocker_result = runner.run(bitlocker_cmd, elevated_required=False, check=False)
        bitlocker = {
            "available": True,
            "exit_code": bitlocker_result.returncode,
            "stdout": bitlocker_result.stdout.strip(),
            "stderr": bitlocker_result.stderr.strip(),
        }

    return {
        "is_windows": is_windows_platform(),
        "is_admin": is_admin(),
        "secure_boot": secure_boot,
        "bitlocker": bitlocker,
        "bcdedit_available": bcdedit_available,
        "bcdboot_available": bcdboot_available,
        "powershell_available": powershell_available,
        "mount_diskimage_available": powershell_available,
        "virtdisk_backend_available": True,
        "report_dir": str(report_dir),
    }


def _ensure_windows_backend_allowed(gate: RealWindowsOpsGate, operation: str, target_path: Path) -> None:
    gate.assert_allowed(
        operation=operation,
        rollback_plan=f"Cleanup target path {target_path}",
        report_path=gate.validation_report_path,
        target_path=target_path,
        require_rollback_plan=True,
        require_report=True,
        require_target_in_lab_dir=True,
    )


def _run_capabilities_scan() -> tuple[dict[str, Any], list[BackendCapability], list[ProbeResult]]:
    capabilities, probes = run_capability_scanners()
    payload = {
        "capabilities": [item.to_dict() for item in capabilities],
        "probes": [item.to_dict() for item in probes],
    }
    return payload, capabilities, probes


def _run_windows_bcd_mutation_smoke(
    *,
    report_dir: Path,
    lab_dir: Path,
    include_displayorder_experiment: bool,
    gate: RealWindowsOpsGate,
) -> StepExecutionResult:
    if not is_windows_platform():
        raise UnsupportedPlatformError(
            "windows-bcd-mutation-smoke can run only on Windows VM."
        )

    if not is_admin():
        raise UnsafeRealOperationError(
            "windows-bcd-mutation-smoke requires administrator privileges."
        )

    backup_path = report_dir / "artifacts" / "windows_bcd_mutation_backup.bcd"
    _ensure_windows_backend_allowed(gate, "validation windows-bcd-mutation-smoke", lab_dir)

    runner = CommandRunner(dry_run=False)
    backend = create_windows_bcd_backend(runner, gate=gate)

    temp_name = "LinuxVHDLauncher TEMP VALIDATION ENTRY - SAFE TO DELETE"
    created_guid: str | None = None
    actions: list[str] = []
    rollback_errors: list[str] = []

    backend.export_backup(backup_path)
    actions.append(f"export backup -> {backup_path}")

    try:
        entry = backend.create_entry(temp_name)
        created_guid = entry.guid
        actions.append(f"create entry -> {created_guid}")

        if include_displayorder_experiment:
            backend.add_to_display_order(created_guid)
            actions.append("add displayorder /addlast")

        backend.delete_entry(created_guid)
        actions.append("delete temporary entry")

        verify = runner.run(
            ["bcdedit", "/enum", "all"],
            elevated_required=True,
            check=False,
        )
        if created_guid in verify.stdout:
            raise ValidationReportFormatError(
                f"Temporary entry {created_guid} still present after delete."
            )
        actions.append("verify deletion")

        rollback = RollbackEvidence(
            planned=True,
            attempted=True,
            status="pass",
            actions=actions,
            errors=[],
        )
    except Exception as exc:  # noqa: BLE001
        if created_guid:
            try:
                backend.delete_entry(created_guid)
                actions.append("rollback delete retry")
            except Exception as rollback_exc:  # noqa: BLE001
                rollback_errors.append(str(rollback_exc))
        status: RollbackStatus = "partial" if created_guid and not rollback_errors else "fail"
        rollback = RollbackEvidence(
            planned=True,
            attempted=created_guid is not None,
            status=status,
            actions=actions,
            errors=rollback_errors or [str(exc)],
        )
        raise StepExecutionError(
            f"{exc}. Emergency cleanup: run `bcdedit /enum all`, "
            f"delete temporary entry {created_guid or '<unknown-guid>'}, "
            f"and restore backup {backup_path}.",
            rollback_evidence=rollback,
        ) from exc

    return StepExecutionResult(
        payload={
            "backup_path": str(backup_path),
            "temporary_entry_name": temp_name,
            "guid": created_guid,
            "displayorder_experiment": include_displayorder_experiment,
            "rollback_status": rollback.status,
        },
        rollback_evidence=rollback,
    )


def _run_validation_command(args: argparse.Namespace) -> int:
    report_dir = Path(args.report_dir) if getattr(args, "report_dir", None) else None

    if args.validation_command == "init":
        doctor_payload = _doctor()
        doctor_report = DoctorReport.from_dict(doctor_payload)
        if report_dir is None:
            report_dir = create_report_directory(Path.cwd())
        else:
            report_dir.mkdir(parents=True, exist_ok=True)
        campaign_id = f"campaign-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        doctor_file = report_dir / "doctor_initial.json"
        doctor_file.write_text(json.dumps(doctor_payload, indent=2) + "\n", encoding="utf-8")

        report = create_initial_report(
            report_dir=report_dir,
            host=doctor_report,
            campaign_id=campaign_id,
            vm_snapshot_name=args.vm_snapshot_name,
        )
        report.environment = _campaign_environment()
        print(json.dumps({"report_dir": str(report_dir), "campaign_id": campaign_id}, indent=2))
        save_report(report_dir, report)
        return 0

    if args.validation_command == "vm-status":
        effective_report_dir = report_dir if report_dir is not None else Path.cwd()
        vm_runner = _build_vm_runner_from_args(args, report_dir=effective_report_dir)
        status = vm_runner.check_status().to_dict()
        print(json.dumps(status, indent=2))
        return 0

    if args.validation_command == "capabilities":
        payload, capabilities, probes = _run_capabilities_scan()
        if report_dir is not None:
            _ensure_report_exists_or_init(report_dir)
            report = load_report(report_dir)
            record_step(
                report=report,
                report_dir=report_dir,
                step_id="capabilities-scan",
                title="validation capabilities",
                command_preview=["linux-vhd-launcher", "validation", "capabilities"],
                docs_url=None,
                body=lambda: StepExecutionResult(
                    payload=payload,
                    probes=probes,
                    capabilities=capabilities,
                ),
            )
            save_report(report_dir, report)

        if bool(args.json):
            print(json.dumps(payload, indent=2))
        else:
            print("Capability Matrix")
            caps_raw = payload.get("capabilities", [])
            if isinstance(caps_raw, list):
                for entry in caps_raw:
                    if isinstance(entry, dict):
                        print(
                            f"- {entry['backend']}/{entry['capability']}: {entry['status']}"
                            + (f" ({entry['reason']})" if entry.get("reason") else "")
                        )
        return 0

    if args.validation_command == "run-campaign":
        if report_dir is None:
            raise ValidationReportFormatError("--report-dir is required for run-campaign.")
        _ensure_report_exists_or_init(report_dir)
        report = load_report(report_dir)
        if report.environment is None:
            report.environment = _campaign_environment()
        vm_runner = _build_vm_runner_from_args(args, report_dir=report_dir)
        vm_runner.before_campaign()

        doctor_payload = _doctor()
        (report_dir / "doctor.json").write_text(
            json.dumps(doctor_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        record_step(
            report=report,
            report_dir=report_dir,
            step_id="campaign-doctor",
            title="doctor",
            command_preview=["linux-vhd-launcher", "doctor", "--json"],
            docs_url=None,
            body=lambda: doctor_payload,
        )
        save_report(report_dir, report)

        capabilities_payload, capabilities, probes = _run_capabilities_scan()
        record_step(
            report=report,
            report_dir=report_dir,
            step_id="campaign-capabilities",
            title="validation capabilities",
            command_preview=["linux-vhd-launcher", "validation", "capabilities", "--json"],
            docs_url=None,
            body=lambda: StepExecutionResult(
                payload=capabilities_payload,
                capabilities=capabilities,
                probes=probes,
            ),
        )
        save_report(report_dir, report)

        installer, registry = build_installer(
            dry_run=True,
            execute_real_windows_ops=False,
            confirmation_token=False,
            backup_path=report_dir / "artifacts" / "bcd_backup_preview.bcd",
            allowed_lab_dir=report_dir,
            validation_report_path=report_path(report_dir),
        )
        (report_dir / "doctor_run_dry.json").write_text(
            json.dumps(doctor_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        run_dry_campaign(
            report_dir=report_dir,
            report=report,
            doctor_payload=doctor_payload,
            installer_plan_factory=lambda iso, vhd, size_gb, _fmt: installer.plan(
                iso,
                VhdSpec(path=vhd, size_gb=size_gb, format="vhdx"),
                dry_run=True,
            ),
            registry_reader=lambda: _registry_payload(registry),
            gate=_build_validation_gate(
                report_dir=report_dir,
                execute_real_windows_ops=False,
                confirmation_token=False,
                dry_run=True,
            ),
        )
        save_report(report_dir, report)

        if bool(args.include_windows_probe):
            gate = _build_validation_gate(
                report_dir=report_dir,
                execute_real_windows_ops=bool(args.execute_real_windows_ops),
                confirmation_token=bool(args.i_understand_this_is_experimental),
                dry_run=not bool(args.no_dry_run),
                allowed_lab_dir=Path(args.lab_dir) if getattr(args, "lab_dir", None) else report_dir,
            )
            record_step(
                report=report,
                report_dir=report_dir,
                step_id="windows-probe",
                title="windows-probe",
                command_preview=["linux-vhd-launcher", "validation", "windows-probe"],
                docs_url=None,
                body=lambda: _run_windows_probe(report_dir, report, gate),
            )
            save_report(report_dir, report)

        if bool(args.include_windows_vhd_smoke):
            gate = _build_validation_gate(
                report_dir=report_dir,
                execute_real_windows_ops=bool(args.execute_real_windows_ops),
                confirmation_token=bool(args.i_understand_this_is_experimental),
                dry_run=not bool(args.no_dry_run),
                allowed_lab_dir=Path(args.lab_dir) if getattr(args, "lab_dir", None) else report_dir,
            )
            smoke_dir = (Path(args.lab_dir) if getattr(args, "lab_dir", None) else report_dir) / "windows_vhd_smoke"
            smoke_dir.mkdir(parents=True, exist_ok=True)
            vhd_path = smoke_dir / "smoke.vhdx"
            _ensure_windows_backend_allowed(gate, "validation windows-vhd-smoke", vhd_path)

            def _smoke_body() -> dict[str, object]:
                if not is_windows_platform():
                    raise UnsupportedPlatformError("windows-vhd-smoke can run only on Windows.")
                backend: VhdBackend
                backend = VirtualDiskApiBackend(gate=gate)
                spec = VhdSpec(path=vhd_path, size_gb=1, format="vhdx")
                attached = False
                try:
                    backend.create_vhd(spec)
                    backend.attach_vhd(vhd_path)
                    attached = True
                    backend.detach_vhd(vhd_path)
                    attached = False
                finally:
                    if attached:
                        backend.detach_vhd(vhd_path)
                    if vhd_path.exists():
                        vhd_path.unlink(missing_ok=True)
                return {"backend": "virtdisk", "path": str(vhd_path)}

            record_step(
                report=report,
                report_dir=report_dir,
                step_id="windows-vhd-smoke",
                title="windows-vhd-smoke",
                command_preview=["linux-vhd-launcher", "validation", "windows-vhd-smoke"],
                docs_url=None,
                body=_smoke_body,
            )
            save_report(report_dir, report)

        if bool(args.include_windows_bcd_backup_smoke):
            gate = _build_validation_gate(
                report_dir=report_dir,
                execute_real_windows_ops=bool(args.execute_real_windows_ops),
                confirmation_token=bool(args.i_understand_this_is_experimental),
                dry_run=not bool(args.no_dry_run),
                allowed_lab_dir=Path(args.lab_dir) if getattr(args, "lab_dir", None) else report_dir,
            )
            backup_path = report_dir / "artifacts" / "windows_bcd_backup_smoke.bcd"
            _ensure_windows_backend_allowed(
                gate,
                "validation windows-bcd-backup-smoke",
                backup_path,
            )

            def _backup_body() -> StepExecutionResult:
                if not is_windows_platform():
                    raise UnsupportedPlatformError(
                        "windows-bcd-backup-smoke can run only on Windows."
                    )
                runner = CommandRunner(dry_run=False)
                bcd_backend = create_windows_bcd_backend(runner, gate=gate)
                bcd_backend.export_backup(backup_path)
                rollback = RollbackEvidence(
                    planned=False,
                    attempted=False,
                    status="not_needed",
                    actions=["export-only operation"],
                    errors=[],
                )
                return StepExecutionResult(
                    payload={"backup_path": str(backup_path)},
                    rollback_evidence=rollback,
                )

            record_step(
                report=report,
                report_dir=report_dir,
                step_id="windows-bcd-backup-smoke",
                title="windows-bcd-backup-smoke",
                command_preview=["linux-vhd-launcher", "validation", "windows-bcd-backup-smoke"],
                docs_url=None,
                body=_backup_body,
            )
            if backup_path.exists():
                add_or_replace_artifact(
                    report,
                    ValidationArtifact(
                        kind="bcd_backup",
                        path=backup_path,
                        sha256=compute_sha256(backup_path),
                        description="BCD export-only smoke backup",
                    ),
                )
            save_report(report_dir, report)

        if bool(args.include_windows_bcd_mutation_smoke):
            if not bool(args.confirm_vm_snapshot):
                raise UnsafeRealOperationError(
                    "windows-bcd-mutation-smoke requires --confirm-vm-snapshot."
                )
            lab_dir_arg = Path(args.lab_dir) if getattr(args, "lab_dir", None) else None
            if lab_dir_arg is None:
                raise UnsafeRealOperationError(
                    "windows-bcd-mutation-smoke requires --lab-dir."
                )

            gate = _build_validation_gate(
                report_dir=report_dir,
                execute_real_windows_ops=bool(args.execute_real_windows_ops),
                confirmation_token=bool(args.i_understand_this_is_experimental),
                dry_run=not bool(args.no_dry_run),
                allowed_lab_dir=lab_dir_arg,
            )
            record_step(
                report=report,
                report_dir=report_dir,
                step_id="windows-bcd-mutation-smoke",
                title="windows-bcd-mutation-smoke",
                command_preview=[
                    "linux-vhd-launcher",
                    "validation",
                    "windows-bcd-mutation-smoke",
                ],
                docs_url=None,
                body=lambda: _run_windows_bcd_mutation_smoke(
                    report_dir=report_dir,
                    lab_dir=lab_dir_arg,
                    include_displayorder_experiment=bool(
                        args.include_displayorder_experiment
                    ),
                    gate=gate,
                ),
            )
            save_report(report_dir, report)

        collect_artifacts(report_dir, report)
        markdown = render_markdown(report)
        (report_dir / "report.md").write_text(markdown, encoding="utf-8")
        save_report(report_dir, report)
        vm_runner.after_campaign()
        print(json.dumps(report.summary.to_dict(), indent=2))
        return 0

    if report_dir is None:
        raise ValidationReportFormatError("--report-dir is required for this validation command.")

    if not report_path(report_dir).exists() and args.validation_command in {
        "run-dry",
        "collect",
        "render",
        "status",
        "windows-probe",
        "windows-vhd-smoke",
        "windows-bcd-backup-smoke",
        "windows-bcd-mutation-smoke",
        "bundle",
    }:
        raise ValidationReportFormatError(
            f"Validation report not found in {report_dir}. Run validation init first."
        )

    report = load_report(report_dir)

    if args.validation_command == "run-dry":
        installer, registry = build_installer(
            dry_run=True,
            execute_real_windows_ops=False,
            confirmation_token=False,
            backup_path=report_dir / "artifacts" / "bcd_backup_preview.bcd",
            allowed_lab_dir=report_dir,
            validation_report_path=report_path(report_dir),
        )
        doctor_payload = _doctor()
        (report_dir / "doctor_run_dry.json").write_text(
            json.dumps(doctor_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        run_dry_campaign(
            report_dir=report_dir,
            report=report,
            doctor_payload=doctor_payload,
            installer_plan_factory=lambda iso, vhd, size_gb, _fmt: installer.plan(
                iso,
                VhdSpec(path=vhd, size_gb=size_gb, format="vhdx"),
                dry_run=True,
            ),
            registry_reader=lambda: _registry_payload(registry),
            gate=_build_validation_gate(
                report_dir=report_dir,
                execute_real_windows_ops=False,
                confirmation_token=False,
                dry_run=True,
            ),
        )
        save_report(report_dir, report)
        print(json.dumps(report.summary.to_dict(), indent=2))
        return 0

    if args.validation_command == "collect":
        collect_artifacts(report_dir, report)
        save_report(report_dir, report)
        print(json.dumps({"artifacts": len(report.artifacts)}, indent=2))
        return 0

    if args.validation_command == "render":
        markdown = render_markdown(report)
        markdown_path = report_dir / "report.md"
        markdown_path.write_text(markdown, encoding="utf-8")
        print(json.dumps({"report_markdown": str(markdown_path)}, indent=2))
        return 0

    if args.validation_command == "status":
        print(json.dumps(report.summary.to_dict(), indent=2))
        return 0

    if args.validation_command == "windows-probe":
        gate = _build_validation_gate(
            report_dir=report_dir,
            execute_real_windows_ops=bool(args.execute_real_windows_ops),
            confirmation_token=bool(args.i_understand_this_is_experimental),
            dry_run=not bool(args.no_dry_run),
        )
        _assert_windows_probe_allowed(gate)
        record_step(
            report=report,
            report_dir=report_dir,
            step_id="windows-probe",
            title="windows-probe",
            command_preview=["linux-vhd-launcher", "validation", "windows-probe"],
            docs_url=None,
            body=lambda: _run_windows_probe(report_dir, report, gate),
        )
        save_report(report_dir, report)
        print(json.dumps(report.summary.to_dict(), indent=2))
        return 0

    if args.validation_command == "windows-vhd-smoke":
        gate = _build_validation_gate(
            report_dir=report_dir,
            execute_real_windows_ops=bool(args.execute_real_windows_ops),
            confirmation_token=bool(args.i_understand_this_is_experimental),
            dry_run=not bool(args.no_dry_run),
        )
        smoke_dir = report_dir / "windows_vhd_smoke"
        smoke_dir.mkdir(parents=True, exist_ok=True)
        vhd_path = smoke_dir / "smoke.vhdx"
        _ensure_windows_backend_allowed(gate, "validation windows-vhd-smoke", vhd_path)

        def _smoke_body() -> dict[str, object]:
            if not is_windows_platform():
                raise UnsupportedPlatformError("windows-vhd-smoke can run only on Windows.")

            runner = CommandRunner(dry_run=False)
            backend: VhdBackend
            if args.backend == "virtdisk":
                backend = VirtualDiskApiBackend(gate=gate)
            else:
                backend = DiskPartVhdBackend(runner=runner, gate=gate)

            spec = VhdSpec(path=vhd_path, size_gb=1, format="vhdx")
            attached = False
            rollback = {"detached": False, "deleted": False}
            try:
                backend.create_vhd(spec)
                backend.attach_vhd(vhd_path)
                attached = True
                backend.detach_vhd(vhd_path)
                attached = False
            finally:
                if attached:
                    try:
                        backend.detach_vhd(vhd_path)
                        rollback["detached"] = True
                    except Exception:
                        rollback["detached"] = False
                if vhd_path.exists():
                    try:
                        vhd_path.unlink(missing_ok=True)
                        rollback["deleted"] = True
                    except Exception:
                        rollback["deleted"] = False
            return {
                "backend": args.backend,
                "path": str(vhd_path),
                "rollback": rollback,
            }

        record_step(
            report=report,
            report_dir=report_dir,
            step_id="windows-vhd-smoke",
            title="windows-vhd-smoke",
            command_preview=["linux-vhd-launcher", "validation", "windows-vhd-smoke"],
            docs_url=None,
            body=_smoke_body,
        )
        save_report(report_dir, report)
        print(json.dumps(report.summary.to_dict(), indent=2))
        return 0

    if args.validation_command == "windows-bcd-backup-smoke":
        gate = _build_validation_gate(
            report_dir=report_dir,
            execute_real_windows_ops=bool(args.execute_real_windows_ops),
            confirmation_token=bool(args.i_understand_this_is_experimental),
            dry_run=not bool(args.no_dry_run),
        )
        backup_path = report_dir / "artifacts" / "windows_bcd_backup_smoke.bcd"
        _ensure_windows_backend_allowed(
            gate,
            "validation windows-bcd-backup-smoke",
            backup_path,
        )

        def _backup_body() -> StepExecutionResult:
            if not is_windows_platform():
                raise UnsupportedPlatformError(
                    "windows-bcd-backup-smoke can run only on Windows."
                )
            runner = CommandRunner(dry_run=False)
            bcd_backend = create_windows_bcd_backend(runner, gate=gate)
            bcd_backend.export_backup(backup_path)
            rollback = RollbackEvidence(
                planned=False,
                attempted=False,
                status="not_needed",
                actions=["export-only operation"],
                errors=[],
            )
            return StepExecutionResult(
                payload={"backup_path": str(backup_path)},
                rollback_evidence=rollback,
            )

        record_step(
            report=report,
            report_dir=report_dir,
            step_id="windows-bcd-backup-smoke",
            title="windows-bcd-backup-smoke",
            command_preview=["linux-vhd-launcher", "validation", "windows-bcd-backup-smoke"],
            docs_url=None,
            body=_backup_body,
        )
        if backup_path.exists():
            add_or_replace_artifact(
                report,
                ValidationArtifact(
                    kind="bcd_backup",
                    path=backup_path,
                    sha256=compute_sha256(backup_path),
                    description="BCD export-only smoke backup",
                ),
            )
        save_report(report_dir, report)
        print(json.dumps(report.summary.to_dict(), indent=2))
        return 0

    if args.validation_command == "windows-bcd-mutation-smoke":
        if not bool(args.confirm_vm_snapshot):
            raise UnsafeRealOperationError(
                "windows-bcd-mutation-smoke requires --confirm-vm-snapshot."
            )
        if not bool(args.execute_real_windows_ops):
            raise UnsafeRealOperationError(
                "windows-bcd-mutation-smoke requires --execute-real-windows-ops."
            )
        if not bool(args.i_understand_this_is_experimental):
            raise UnsafeRealOperationError(
                "windows-bcd-mutation-smoke requires --i-understand-this-is-experimental."
            )
        if not bool(args.no_dry_run):
            raise UnsafeRealOperationError(
                "windows-bcd-mutation-smoke requires --no-dry-run."
            )
        if not is_windows_platform():
            raise UnsupportedPlatformError(
                "windows-bcd-mutation-smoke can run only on Windows VM."
            )
        if not is_admin():
            raise UnsafeRealOperationError(
                "windows-bcd-mutation-smoke requires administrator privileges."
            )

        lab_dir = Path(args.lab_dir)
        lab_dir.mkdir(parents=True, exist_ok=True)
        gate = _build_validation_gate(
            report_dir=report_dir,
            execute_real_windows_ops=True,
            confirmation_token=True,
            dry_run=False,
            allowed_lab_dir=lab_dir,
        )
        step = record_step(
            report=report,
            report_dir=report_dir,
            step_id="windows-bcd-mutation-smoke",
            title="windows-bcd-mutation-smoke",
            command_preview=[
                "linux-vhd-launcher",
                "validation",
                "windows-bcd-mutation-smoke",
            ],
            docs_url=None,
            body=lambda: _run_windows_bcd_mutation_smoke(
                report_dir=report_dir,
                lab_dir=lab_dir,
                include_displayorder_experiment=bool(args.include_displayorder_experiment),
                gate=gate,
            ),
        )
        if step.status != "pass":
            report.notes.append(
                "EMERGENCY CLEANUP: run bcdedit /enum all, delete temporary validation "
                "entry if present, and restore BCD backup artifact."
            )
        save_report(report_dir, report)
        print(json.dumps(report.summary.to_dict(), indent=2))
        return 0

    if args.validation_command == "bundle":
        bundle_path = create_artifact_bundle(
            report_dir=report_dir,
            report=report,
            options=BundleOptions(
                redact=bool(args.redact),
                format="zip" if args.format == "zip" else "targz",
            ),
        )
        save_report(report_dir, report)
        print(json.dumps({"bundle": str(bundle_path)}, indent=2))
        return 0

    raise ValidationReportFormatError(
        f"Unsupported validation command: {args.validation_command}"
    )


def _demo_context_from_args(args: argparse.Namespace) -> DemoContext:
    return DemoContext(
        lab_dir=Path(args.lab_dir),
        report_dir=Path(args.report_dir),
        dry_run=not bool(getattr(args, "no_dry_run", False)),
        execute_real_windows_ops=bool(getattr(args, "execute_real_windows_ops", False)),
        confirmation_token=bool(getattr(args, "i_understand_this_is_experimental", False)),
        confirm_vm_snapshot=bool(getattr(args, "confirm_vm_snapshot", False)),
    )


def _print_demo_result(result: object, *, as_json: bool) -> None:
    payload: dict[str, object]
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict):
        raw = to_dict()
        payload = raw if isinstance(raw, dict) else {"result": str(raw)}
    else:
        payload = {"result": str(result)}

    if as_json:
        print(json.dumps(payload, indent=2))
        return

    status = payload.get("status", "unknown") if isinstance(payload, dict) else "unknown"
    print(f"status: {status}")
    if isinstance(payload, dict):
        blockers = payload.get("blockers")
        warnings_raw = payload.get("warnings")
        if isinstance(blockers, list) and blockers:
            print("blockers:")
            for blocker in blockers:
                print(f"- {blocker}")
        if isinstance(warnings_raw, list) and warnings_raw:
            print("warnings:")
            for warning in warnings_raw:
                print(f"- {warning}")


def _resolve_demo_uninstall_guid(*, report_dir: Path, explicit_guid: str | None) -> str:
    if explicit_guid:
        return explicit_guid
    manifest_path = report_dir / "live_registration_manifest.json"
    if not manifest_path.exists():
        raise UnsafeRealOperationError(
            "GUID is required when registration manifest is missing."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    guid = str(manifest.get("guid", "")).strip()
    if not guid:
        raise UnsafeRealOperationError("Registration manifest does not contain GUID.")
    return guid


def _run_demo_command(args: argparse.Namespace) -> int:
    as_json = bool(getattr(args, "json", False))

    if args.demo_command == "inspect-iso":
        result = demo_inspect_iso(iso_path=Path(args.iso))
        _print_demo_result(result, as_json=as_json)
        return 0

    if args.demo_command != "live":
        raise ValidationReportFormatError(f"Unsupported demo command: {args.demo_command}")

    if args.demo_live_command == "plan":
        result = plan_live(
            iso_path=Path(args.iso),
            vhd_path=Path(args.vhd),
            size_gb=int(args.size_gb),
        )
        _print_demo_result(result, as_json=as_json)
        return 0

    if args.demo_live_command == "mark-boot-result":
        result = mark_boot_result(
            report_dir=Path(args.report_dir),
            result=args.result,
            notes=str(args.notes),
        )
        _print_demo_result(result, as_json=as_json)
        return 0

    context = _demo_context_from_args(args)

    if args.demo_live_command == "build-vhd":
        result = build_payload(
            context=context,
            iso_path=Path(args.iso),
            vhd_path=Path(args.vhd),
            size_gb=int(args.size_gb),
        )
        _print_demo_result(result, as_json=as_json)
        return 0

    if args.demo_live_command == "register-bcd":
        result = register_live(
            context=context,
            vhd_path=Path(args.vhd),
            strategy=str(args.strategy),
        )
        _print_demo_result(result, as_json=as_json)
        return 2 if result.status == "registration_blocked" else 0

    if args.demo_live_command == "install":
        result = install_live(
            context=context,
            iso_path=Path(args.iso),
            vhd_path=Path(args.vhd),
            size_gb=int(args.size_gb),
            strategy=str(args.strategy),
        )
        _print_demo_result(result, as_json=as_json)
        return 2 if result.status == "registration_blocked" else 0

    if args.demo_live_command == "uninstall":
        guid = _resolve_demo_uninstall_guid(
            report_dir=context.report_dir,
            explicit_guid=str(args.guid) if args.guid else None,
        )
        result = uninstall_live(
            context=context,
            guid=guid,
            delete_vhd=bool(args.delete_vhd),
            vhd_path=Path(args.vhd) if args.vhd is not None else None,
        )
        _print_demo_result(result, as_json=as_json)
        return 0

    raise ValidationReportFormatError(
        f"Unsupported demo live command: {args.demo_live_command}"
    )


def main(argv: list[str] | None = None) -> int:
    """CLI main entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    dry_run = bool(getattr(args, "dry_run", False))
    output_format = "json" if getattr(args, "json", False) else getattr(
        args,
        "output_format",
        getattr(args, "format", "text"),
    )

    try:
        if args.command == "validation":
            return _run_validation_command(args)
        if args.command == "demo":
            return _run_demo_command(args)

        if args.command == "doctor":
            doctor_payload = _doctor()
            if output_format == "json":
                print(json.dumps(doctor_payload, indent=2))
            else:
                print("Doctor")
                for key, value in doctor_payload.items():
                    print(f"- {key}: {value}")
            return 0

        installer, registry = build_installer(
            dry_run=dry_run,
            execute_real_windows_ops=bool(getattr(args, "execute_real_windows_ops", False)),
            confirmation_token=bool(
                getattr(args, "i_understand_this_is_experimental", False)
            ),
            backup_path=getattr(args, "bcd_backup_path", None),
        )

        if args.command == "scan-iso":
            images = installer.iso_manager.scan_directory(args.directory)
            print(json.dumps([{"path": str(i.path), "size_bytes": i.size_bytes} for i in images], indent=2))
            return 0

        if args.command == "plan-install":
            spec = _spec_from_args(args)
            plan = installer.plan(args.iso, spec, dry_run=dry_run)
            if output_format == "json":
                print(json.dumps(plan.to_dict(), indent=2))
            else:
                _render_operation_plan(plan.to_dict())
            return 0

        if args.command == "plan-windows-lab":
            plan = build_windows_lab_plan()
            if output_format == "json":
                print(json.dumps(plan.to_dict(), indent=2))
            else:
                _render_operation_plan(plan.to_dict())
            return 0

        if args.command == "install":
            spec = _spec_from_args(args)
            result = installer.install(
                InstallRequest(
                    iso_path=args.iso,
                    vhd_spec=spec,
                    description=args.description,
                    bcd_backup_path=args.bcd_backup_path,
                    dry_run=dry_run,
                )
            )
            print(
                json.dumps(
                    {
                        "success": result.success,
                        "bcd_guid": result.bcd_guid,
                        "bcd_backup_path": str(result.bcd_backup_path)
                        if result.bcd_backup_path
                        else None,
                        "warnings": result.warnings,
                        "notice": (
                            "Boot entry generation is experimental and must be validated "
                            "on a Windows VM before production use."
                        ),
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "uninstall":
            installer.uninstall(args.guid, args.vhd)
            print(json.dumps({"success": True, "guid": args.guid}, indent=2))
            return 0

        if args.command == "show-registry":
            items = registry.list_items()
            if not items:
                print("Registry is empty.")
                return 0

            payload = [
                {
                    "distro": item.distro,
                    "vhd_path": str(item.vhd_path),
                    "bcd_guid": item.bcd_guid,
                    "created_at": item.created_at.isoformat(),
                    "bcd_backup_path": str(item.bcd_backup_path) if item.bcd_backup_path else None,
                }
                for item in items
            ]
            print(json.dumps(payload, indent=2))
            return 0
    except RegistryFormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except LinuxVhdLauncherError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
