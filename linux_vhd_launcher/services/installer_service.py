"""Installation orchestration and rollback chain."""

from __future__ import annotations

import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from linux_vhd_launcher.errors import ExperimentalBootChainWarning, RollbackError
from linux_vhd_launcher.models import IsoImage, LinuxDistribution, OperationPlan, VhdSpec
from linux_vhd_launcher.services.boot_manager import BootManager
from linux_vhd_launcher.services.iso_manager import ISOManager
from linux_vhd_launcher.services.operation_planners import (
    FullInstallPlanner,
)
from linux_vhd_launcher.services.secure_boot_helper import SecureBootHelper
from linux_vhd_launcher.services.vhd_manager import VHDManager

logger = logging.getLogger(__name__)
RollbackAction = tuple[str, Callable[[], object]]


class DeploymentBackend(Protocol):
    """Interface for Linux payload preparation inside mounted VHD."""

    def prepare(self, distro: LinuxDistribution, vhd_spec: VhdSpec) -> Path:
        """Prepare deployment payload and return boot files staging path."""
        ...


@dataclass(slots=True)
class FakeDeploymentBackend:
    """Placeholder deployment backend for current prototype and tests."""

    fail: bool = False

    def prepare(self, distro: LinuxDistribution, vhd_spec: VhdSpec) -> Path:
        if self.fail:
            raise RuntimeError("Deployment backend failed")
        staging = vhd_spec.path.parent / f"{vhd_spec.path.stem}_staging"
        (staging / "EFI/BOOT").mkdir(parents=True, exist_ok=True)
        (staging / "EFI/BOOT/BOOTX64.EFI").write_text("shim", encoding="utf-8")
        (staging / "EFI/BOOT/grubx64.efi").write_text("grub", encoding="utf-8")
        return staging


@dataclass(slots=True)
class InstallRequest:
    """Input parameters for installation workflow."""

    iso_path: Path
    vhd_spec: VhdSpec
    description: str
    bcd_backup_path: Path | None = None
    dry_run: bool = False


@dataclass(slots=True)
class InstallResult:
    """Output of installation workflow."""

    success: bool
    bcd_guid: str | None
    bcd_backup_path: Path | None
    warnings: list[str]


@dataclass(slots=True)
class InstallerService:
    """Coordinates validation, VHD setup, deployment, BCD update, and rollback."""

    iso_manager: ISOManager
    vhd_manager: VHDManager
    boot_manager: BootManager
    secure_boot_helper: SecureBootHelper
    deployment_backend: DeploymentBackend

    def plan(self, iso_path: Path, vhd_spec: VhdSpec, *, dry_run: bool) -> OperationPlan:
        """Validate input and return a structured execution plan."""
        self.iso_manager.validate_iso(iso_path)
        self.vhd_manager.check_free_space(vhd_spec.path, vhd_spec.size_gb)
        backup_path = vhd_spec.path.parent / "bcd_backup_preview.bcd"
        planner = FullInstallPlanner.from_defaults(self.boot_manager.command_builder)
        return planner.build(
            iso_path=iso_path,
            vhd_spec=vhd_spec,
            dry_run=dry_run,
            bcd_backup_path=backup_path,
        )

    def install(self, request: InstallRequest) -> InstallResult:
        """Run installation scenario with rollback support."""
        bcd_guid: str | None = None
        bcd_backup_path: Path | None = None
        warnings_out: list[str] = []
        distro_name = "Unknown Linux"
        rollback_stack: list[RollbackAction] = []

        try:
            logger.info("Step 1/11 validate environment")
            self.iso_manager.validate_iso(request.iso_path)

            logger.info("Step 2/11 validate ISO and metadata")
            iso = self.iso_manager.build_iso(request.iso_path, with_sha256=True)
            distro = self._resolve_distribution(iso)
            distro_name = distro.name

            logger.info("Step 3/11 check free space")
            self.vhd_manager.check_free_space(request.vhd_spec.path, request.vhd_spec.size_gb)

            logger.info("Step 4/11 create VHD")
            self.vhd_manager.create(request.vhd_spec)
            rollback_stack.append(
                (
                    "cleanup_vhd_file",
                    lambda: self.vhd_manager.cleanup_vhd_file(request.vhd_spec.path),
                )
            )

            logger.info("Step 5/11 attach VHD")
            self.vhd_manager.attach(request.vhd_spec.path)
            rollback_stack.append(("detach_vhd", lambda: self.vhd_manager.detach(request.vhd_spec.path)))

            logger.info("Step 6/11 prepare deployment placeholder")
            staging_root = self.deployment_backend.prepare(distro, request.vhd_spec)

            logger.info("Step 7/11 verify boot files")
            warnings_out.extend(self.secure_boot_helper.verify_boot_files(staging_root, distro))

            logger.info("Step 8/11 backup BCD")
            if request.bcd_backup_path is not None:
                bcd_backup_path = request.bcd_backup_path
            else:
                backup_name = f"bcd_backup_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.bcd"
                bcd_backup_path = request.vhd_spec.path.parent / backup_name
            self.boot_manager.export_backup(bcd_backup_path)

            logger.info("Step 9/11 create BCD entry")
            drive = request.vhd_spec.path.drive or "<drive>"
            device = f"vhd=[{drive}]\\{request.vhd_spec.path.name}"
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ExperimentalBootChainWarning)
                entry = self.boot_manager.create_entry(
                    description=request.description,
                    device=device,
                    loader_path=r"\EFI\BOOT\BOOTX64.EFI",
                )
            for warning_item in caught:
                warnings_out.append(str(warning_item.message))

            bcd_guid = entry.guid
            rollback_stack.append(("delete_bcd_entry", lambda: self.boot_manager.delete_entry(entry.guid)))

            logger.info("Step 10/11 save registry entry")
            self.boot_manager.save_registry_item(
                distro=distro_name,
                vhd_path=request.vhd_spec.path,
                bcd_guid=entry.guid,
                bcd_backup_path=bcd_backup_path,
            )
            rollback_stack.append(
                ("remove_registry_item", lambda: self.boot_manager.remove_registry_item(entry.guid))
            )

            logger.info("Step 11/11 detach VHD")
            self.vhd_manager.detach(request.vhd_spec.path)

            return InstallResult(
                success=True,
                bcd_guid=bcd_guid,
                bcd_backup_path=bcd_backup_path,
                warnings=warnings_out,
            )
        except Exception as exc:
            rollback_errors = self._run_rollback(rollback_stack, bcd_backup_path)
            if rollback_errors:
                joined = "; ".join(rollback_errors)
                raise RollbackError(
                    f"Installation failed: {exc}. Rollback failures: {joined}"
                ) from exc
            raise

    def uninstall(self, guid: str, vhd_path: Path) -> None:
        """Remove BCD entry and registry record, then detach VHD if needed."""
        self.boot_manager.delete_entry(guid)
        self.boot_manager.remove_registry_item(guid)
        try:
            self.vhd_manager.detach(vhd_path)
        except Exception:
            logger.warning("VHD detach during uninstall failed for %s", vhd_path)

    def _resolve_distribution(self, iso: IsoImage) -> LinuxDistribution:
        distro = self.iso_manager.match_catalog(iso)
        if distro is not None:
            return distro
        return LinuxDistribution(
            name=iso.name,
            version="unknown",
            iso=iso,
            recommended_size_gb=40,
            secure_boot_supported=False,
        )

    def _run_rollback(
        self,
        rollback_stack: list[RollbackAction],
        bcd_backup_path: Path | None,
    ) -> list[str]:
        errors: list[str] = []
        for action_name, action in reversed(rollback_stack):
            try:
                action()
                logger.info("rollback success: %s", action_name)
            except Exception as rollback_exc:
                message = f"{action_name}: {rollback_exc}"
                logger.error("rollback failure: %s", message)
                errors.append(message)

        if bcd_backup_path is not None:
            logger.warning("BCD backup retained at: %s", bcd_backup_path)
        return errors
