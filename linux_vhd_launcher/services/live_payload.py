"""Live ISO inspection and VHD payload build planning/execution."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from linux_vhd_launcher.errors import UnsafeRealOperationError, UnsupportedPlatformError
from linux_vhd_launcher.models import LiveIsoInfo, LiveVhdBuildPlan, LiveVhdLayout, PlannedStep
from linux_vhd_launcher.services.grub_config import (
    GrubLiveIsoConfig,
    generate_ubuntu_loopback_grub_cfg,
)
from linux_vhd_launcher.system.runner import CommandResult, CommandRunner
from linux_vhd_launcher.system.windows_disk_image import (
    DiskImageMounter,
    PowerShellDiskImageMounter,
)
from linux_vhd_launcher.system.windows_privileges import is_admin, is_windows_platform
from linux_vhd_launcher.system.windows_safety import RealWindowsOpsGate

VHD_NATIVE_BOOT_DOCS_URL = (
    "https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/"
    "boot-to-vhd--native-boot--add-a-virtual-hard-disk-to-the-boot-menu?view=windows-11"
)
DISKPART_VDISK_DOCS_URL = (
    "https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/create-vdisk"
)
MOUNT_DISK_IMAGE_DOCS_URL = (
    "https://learn.microsoft.com/en-us/powershell/module/storage/mount-diskimage"
)


@dataclass(slots=True)
class LiveVhdBuildOutcome:
    """Execution result for live VHD payload build."""

    status: Literal["planned", "payload_built"]
    plan: LiveVhdBuildPlan
    layout: LiveVhdLayout
    executed_commands: list[CommandResult] = field(default_factory=list)
    rollback_actions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "plan": self.plan.to_dict(),
            "layout": self.layout.to_dict(),
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
            "notes": self.notes,
        }


def inspect_live_iso(
    iso_path: Path,
    *,
    mounter: DiskImageMounter | None = None,
) -> LiveIsoInfo:
    """Inspect ISO content and collect boot-relevant metadata."""
    if not iso_path.exists():
        raise FileNotFoundError(f"ISO path does not exist: {iso_path}")

    if iso_path.is_dir():
        root = iso_path
        size_bytes = _dir_size_bytes(iso_path)
        sha256 = _sha256_dir(iso_path)
        return _inspect_from_root(iso_path=iso_path, root=root, sha256=sha256, size_bytes=size_bytes)

    size_bytes = iso_path.stat().st_size
    sha256 = _sha256_file(iso_path)

    if mounter is None:
        mounter = PowerShellDiskImageMounter(runner=CommandRunner(dry_run=False))

    mounted = mounter.mount_read_only(iso_path)
    try:
        return _inspect_from_root(
            iso_path=iso_path,
            root=mounted.mount_point,
            sha256=sha256,
            size_bytes=size_bytes,
        )
    finally:
        mounter.dismount(mounted)


def build_live_vhd_layout(
    *,
    iso_info: LiveIsoInfo,
    vhd_path: Path,
    size_gb: int,
    format: Literal["vhdx", "vhd"] = "vhdx",
    efi_partition_size_mb: int = 512,
    data_partition_fs: Literal["ntfs", "exfat", "fat32"] = "ntfs",
) -> LiveVhdLayout:
    """Build a default layout for live payload staging."""
    return LiveVhdLayout(
        vhd_path=vhd_path,
        format=format,
        size_gb=size_gb,
        efi_partition_size_mb=efi_partition_size_mb,
        data_partition_fs=data_partition_fs,
        iso_inside_path=f"/live/{iso_info.iso_path.name}",
        efi_loader_path="/EFI/BOOT/BOOTX64.EFI",
        grub_cfg_path="/EFI/BOOT/grub.cfg",
    )


def build_live_vhd_plan(
    *,
    iso: LiveIsoInfo,
    layout: LiveVhdLayout,
) -> LiveVhdBuildPlan:
    """Create dry-run plan with exact command previews and blockers."""
    blockers: list[str] = []
    warnings: list[str] = [
        "Boot registration is experimental and bootability is unverified until VM reboot test.",
        "Direct Windows Boot Manager chain to Linux EFI inside VHDX is not confirmed.",
    ]

    if not iso.has_efi_boot:
        blockers.append("ISO does not expose EFI/BOOT/BOOTX64.EFI.")
    if not iso.has_casper_kernel or iso.kernel_path is None or iso.initrd_path is None:
        blockers.append("ISO does not expose casper kernel/initrd paths required for loopback boot.")

    steps = [
        PlannedStep(
            id="live-vhd-create",
            title="Create and attach dynamic VHD",
            command_preview=["diskpart", "/s", "<diskpart-create-and-attach-script>"],
            description=(
                f"Create {layout.format.upper()} {layout.vhd_path} ({layout.size_gb} GiB), "
                "attach it, initialize GPT, create EFI + data partitions."
            ),
            dangerous=True,
            rollback=f"Detach and delete partial VHD {layout.vhd_path}",
            docs_url=DISKPART_VDISK_DOCS_URL,
            prerequisites=["Windows admin", "VM snapshot confirmed", "Path inside lab dir"],
            expected_result="Mounted VHD volumes available for copy operations",
            rollback_action=f"diskpart detach + delete {layout.vhd_path}",
            verification_action="Get-DiskImage/Get-Volume confirms mounted partitions",
            risk_level="high",
        ),
        PlannedStep(
            id="live-vhd-copy-iso",
            title="Copy ISO payload into VHD data partition",
            command_preview=[
                "powershell",
                "-NoProfile",
                "Copy-Item <iso> <data>\\live\\<iso-name>",
            ],
            description=(
                "Copy full ISO into data partition (NTFS preferred for >4GB images), "
                "then stage EFI boot files and generated grub.cfg."
            ),
            dangerous=True,
            rollback="Detach and delete partial VHD if copy fails before final detach.",
            docs_url=MOUNT_DISK_IMAGE_DOCS_URL,
            prerequisites=["Step live-vhd-create completed", "ISO mount readable"],
            expected_result="ISO + EFI files present inside VHD payload",
            rollback_action="Remove staged payload and delete VHD when build aborted",
            verification_action="Hash/size of copied ISO and presence of grub.cfg",
            risk_level="high",
        ),
        PlannedStep(
            id="live-vhd-detach",
            title="Detach VHD and persist artifacts",
            command_preview=["diskpart", "/s", "<diskpart-detach-script>"],
            description="Detach VHD and write build report artifacts (plan, iso info, hashes).",
            dangerous=True,
            rollback="If detach fails, retry detach and stop before any boot registration.",
            docs_url=DISKPART_VDISK_DOCS_URL,
            prerequisites=["Step live-vhd-copy-iso completed"],
            expected_result="VHD file is closed and ready for optional registration experiment",
            rollback_action="Retry detach; do not mutate BCD",
            verification_action="No attached disk image for target VHD",
            risk_level="medium",
        ),
    ]

    return LiveVhdBuildPlan(
        iso=iso,
        layout=layout,
        steps=steps,
        warnings=warnings,
        blockers=blockers,
        experimental=True,
    )


def build_live_vhd(
    *,
    iso: LiveIsoInfo,
    layout: LiveVhdLayout,
    lab_dir: Path,
    report_dir: Path,
    dry_run: bool,
    execute_real_windows_ops: bool,
    confirmation_token: bool,
    confirm_vm_snapshot: bool,
    gate: RealWindowsOpsGate | None = None,
    runner: CommandRunner | None = None,
    mounter: DiskImageMounter | None = None,
) -> LiveVhdBuildOutcome:
    """Build live ISO VHD payload (or dry-run plan)."""
    plan = build_live_vhd_plan(iso=iso, layout=layout)
    outcome = LiveVhdBuildOutcome(status="planned", plan=plan, layout=layout)

    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "LiveIsoInfo.json").write_text(
        json.dumps(iso.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "LiveVhdBuildPlan.json").write_text(
        json.dumps(plan.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )

    if dry_run:
        outcome.notes.append("Dry-run only. No real Windows disk mutation executed.")
        return outcome

    if plan.blockers:
        raise UnsafeRealOperationError(
            "Refusing real build because plan has blockers: " + "; ".join(plan.blockers)
        )

    if not is_windows_platform():
        raise UnsupportedPlatformError("Real live VHD build is supported only on Windows.")
    if not is_admin():
        raise UnsafeRealOperationError("Real live VHD build requires administrator privileges.")
    if not confirm_vm_snapshot:
        raise UnsafeRealOperationError("Real live VHD build requires --confirm-vm-snapshot.")

    if gate is None:
        gate = RealWindowsOpsGate(
            execute_real_windows_ops=execute_real_windows_ops,
            confirmation_token=confirmation_token,
            dry_run=False,
            backup_path=report_dir / "bcd_pre_registration_backup.bcd",
            allowed_lab_dir=lab_dir,
            validation_report_path=report_dir / "demo_report.json",
        )

    gate.assert_allowed(
        operation="demo live build-vhd",
        rollback_plan=f"Detach and delete partial VHD {layout.vhd_path}",
        report_path=report_dir / "demo_report.json",
        target_path=layout.vhd_path,
        require_rollback_plan=True,
        require_report=True,
        require_target_in_lab_dir=True,
    )

    if mounter is None:
        mounter = PowerShellDiskImageMounter(runner=CommandRunner(dry_run=False))
    if runner is None:
        runner = CommandRunner(dry_run=False)

    mounted = None
    efi_letter = "S"
    data_letter = "T"

    try:
        create_script = _diskpart_create_script(
            layout=layout,
            efi_drive_letter=efi_letter,
            data_drive_letter=data_letter,
        )
        outcome.executed_commands.append(_run_diskpart_script(runner, create_script))

        mounted = mounter.mount_read_only(iso.iso_path)

        copy_iso_cmd = (
            "New-Item -ItemType Directory -Force -Path '{dst}\\live' | Out-Null; "
            "Copy-Item -LiteralPath '{src}' -Destination '{dst}\\live\\{name}' -Force"
        ).format(
            dst=f"{data_letter}:",
            src=_escape_ps_single_quoted(str(iso.iso_path)),
            name=iso.iso_path.name,
        )
        outcome.executed_commands.append(
            runner.run(
                ["powershell", "-NoProfile", "-Command", copy_iso_cmd],
                elevated_required=True,
                check=True,
            )
        )

        copy_efi_cmd = (
            "New-Item -ItemType Directory -Force -Path '{efi}\\EFI\\BOOT' | Out-Null; "
            "Copy-Item -Path '{src}\\EFI\\BOOT\\*' -Destination '{efi}\\EFI\\BOOT\\' "
            "-Recurse -Force"
        ).format(
            efi=f"{efi_letter}:",
            src=_escape_ps_single_quoted(str(mounted.mount_point)),
        )
        outcome.executed_commands.append(
            runner.run(
                ["powershell", "-NoProfile", "-Command", copy_efi_cmd],
                elevated_required=True,
                check=True,
            )
        )

        if iso.kernel_path is None or iso.initrd_path is None:
            raise UnsafeRealOperationError(
                "kernel/initrd paths are missing; refusing to generate grub.cfg"
            )

        grub_cfg = generate_ubuntu_loopback_grub_cfg(
            GrubLiveIsoConfig(
                iso_inside_path=layout.iso_inside_path,
                kernel_path=iso.kernel_path,
                initrd_path=iso.initrd_path,
            )
        )
        grub_target = Path(f"{efi_letter}:/") / layout.grub_cfg_path.lstrip("/")
        grub_target.parent.mkdir(parents=True, exist_ok=True)
        grub_target.write_text(grub_cfg, encoding="utf-8")

        artifact_hashes = {
            "vhd_sha256": _sha256_file(layout.vhd_path),
            "grub_cfg_sha256": hashlib.sha256(grub_cfg.encode("utf-8")).hexdigest(),
        }
        (report_dir / "live_vhd_artifact_hashes.json").write_text(
            json.dumps(artifact_hashes, indent=2) + "\n",
            encoding="utf-8",
        )

        outcome.executed_commands.append(_run_diskpart_script(runner, _diskpart_detach_script(layout.vhd_path)))
        outcome.status = "payload_built"
        return outcome
    except Exception:
        try:
            outcome.executed_commands.append(
                _run_diskpart_script(runner, _diskpart_detach_script(layout.vhd_path), check=False)
            )
            outcome.rollback_actions.append(f"detached {layout.vhd_path}")
        except Exception as detach_exc:  # noqa: BLE001
            outcome.rollback_actions.append(f"detach failed: {detach_exc}")

        if layout.vhd_path.exists():
            try:
                layout.vhd_path.unlink(missing_ok=True)
                outcome.rollback_actions.append(f"deleted partial VHD {layout.vhd_path}")
            except Exception as delete_exc:  # noqa: BLE001
                outcome.rollback_actions.append(f"partial VHD cleanup failed: {delete_exc}")
        raise
    finally:
        if mounted is not None:
            try:
                mounter.dismount(mounted)
            except Exception as exc:  # noqa: BLE001
                outcome.rollback_actions.append(f"ISO dismount warning: {exc}")


def _inspect_from_root(*, iso_path: Path, root: Path, sha256: str, size_bytes: int) -> LiveIsoInfo:
    rel_files = _collect_relative_files(root)
    rel_lower = {item.lower(): item for item in rel_files}

    kernel_path = _pick_first(
        rel_lower,
        [
            "casper/vmlinuz",
            "casper/vmlinuz.efi",
            "casper/vmlinuz-generic",
        ],
    )
    initrd_path = _pick_first(
        rel_lower,
        [
            "casper/initrd",
            "casper/initrd.lz",
            "casper/initrd.gz",
            "casper/initrd.img",
            "casper/initrd.zst",
        ],
    )

    stem = iso_path.stem.lower()
    distro = "Ubuntu" if "ubuntu" in stem else "Unknown"
    version_match = re.search(r"(\d{2}\.\d{2}(?:\.\d+)?)", stem)
    version = version_match.group(1) if version_match else None

    has_shim = any(
        rel.startswith("efi/") and Path(rel).name.lower().startswith("shim") and rel.endswith(".efi")
        for rel in rel_lower
    )
    has_grub = any(
        Path(rel).name.lower() in {"grubx64.efi", "grub.cfg"}
        for rel in rel_lower
    )

    return LiveIsoInfo(
        iso_path=iso_path,
        distro=distro,
        version=version,
        sha256=sha256,
        size_bytes=size_bytes,
        has_efi_boot="efi/boot/bootx64.efi" in rel_lower,
        has_shim=has_shim,
        has_grub=has_grub,
        has_casper_kernel=kernel_path is not None,
        kernel_path=f"/{kernel_path}" if kernel_path is not None else None,
        initrd_path=f"/{initrd_path}" if initrd_path is not None else None,
    )


def _pick_first(files: dict[str, str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in files:
            return files[candidate]
    return None


def _collect_relative_files(root: Path) -> list[str]:
    out: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        out.append(path.relative_to(root).as_posix())
    return out


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _sha256_dir(path: Path) -> str:
    hasher = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        rel = child.relative_to(path).as_posix().encode("utf-8")
        hasher.update(rel)
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def _run_diskpart_script(runner: CommandRunner, script: str, *, check: bool = True) -> CommandResult:
    with NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as handle:
        handle.write(script)
        script_path = Path(handle.name)

    try:
        return runner.run(["diskpart", "/s", str(script_path)], elevated_required=True, check=check)
    finally:
        script_path.unlink(missing_ok=True)


def _diskpart_create_script(
    *,
    layout: LiveVhdLayout,
    efi_drive_letter: str,
    data_drive_letter: str,
) -> str:
    max_mb = layout.size_gb * 1024
    return "\n".join(
        [
            f'create vdisk file="{layout.vhd_path}" maximum={max_mb} type=expandable',
            f'select vdisk file="{layout.vhd_path}"',
            "attach vdisk",
            "convert gpt",
            f"create partition efi size={layout.efi_partition_size_mb}",
            "format quick fs=fat32 label=LVH_EFI",
            f"assign letter={efi_drive_letter}",
            "create partition primary",
            f"format quick fs={layout.data_partition_fs} label=LVH_DATA",
            f"assign letter={data_drive_letter}",
        ]
    )


def _diskpart_detach_script(path: Path) -> str:
    return "\n".join(
        [
            f'select vdisk file="{path}"',
            "detach vdisk",
        ]
    )


def _escape_ps_single_quoted(value: str) -> str:
    return value.replace("'", "''")
