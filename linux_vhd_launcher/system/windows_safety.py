"""Safety gate for real Windows operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from linux_vhd_launcher.errors import UnsafeRealOperationError
from linux_vhd_launcher.system.windows_privileges import is_admin, is_windows_platform


@dataclass(slots=True)
class RealWindowsOpsGate:
    """Explicit guard for potentially destructive real Windows operations."""

    execute_real_windows_ops: bool
    confirmation_token: bool
    dry_run: bool
    backup_path: Path | None
    allowed_lab_dir: Path | None = None
    validation_report_path: Path | None = None
    platform_checker: Callable[[], bool] = is_windows_platform
    admin_checker: Callable[[], bool] = is_admin

    def assert_allowed(
        self,
        *,
        operation: str,
        rollback_plan: str | None = None,
        report_path: Path | None = None,
        target_path: Path | None = None,
        require_rollback_plan: bool = False,
        require_report: bool = False,
        require_target_in_lab_dir: bool = False,
    ) -> None:
        """Raise if guard requirements are not fully satisfied."""
        missing: list[str] = []
        if not self.platform_checker():
            missing.append("OS must be Windows")
        if not self.admin_checker():
            missing.append("administrator rights are required")
        if not self.execute_real_windows_ops:
            missing.append("--execute-real-windows-ops flag is required")
        if self.dry_run:
            missing.append("dry-run must be disabled")
        if self.backup_path is None:
            missing.append("BCD backup path must be configured")
        if not self.confirmation_token:
            missing.append("--i-understand-this-is-experimental token is required")
        if require_rollback_plan and not rollback_plan:
            missing.append("rollback plan must be defined")

        effective_report = report_path if report_path is not None else self.validation_report_path
        if require_report and effective_report is None:
            missing.append("validation report path must be configured")

        if require_target_in_lab_dir:
            if target_path is None:
                missing.append("target path must be provided")
            elif self.allowed_lab_dir is None:
                missing.append("allowed lab directory must be configured")
            elif not _is_within(target_path, self.allowed_lab_dir):
                missing.append(
                    f"target path must be inside allowed lab directory: {self.allowed_lab_dir}"
                )

        if missing:
            raise UnsafeRealOperationError(
                f"Refusing real Windows operation '{operation}'. Missing safety conditions: "
                + "; ".join(missing)
            )


def allow_all_operations_gate(*, backup_path: Path | None) -> RealWindowsOpsGate:
    """Factory primarily for tests where all conditions are intentionally enabled."""
    return RealWindowsOpsGate(
        execute_real_windows_ops=True,
        confirmation_token=True,
        dry_run=False,
        backup_path=backup_path,
        allowed_lab_dir=None,
        validation_report_path=None,
        platform_checker=lambda: True,
        admin_checker=lambda: True,
    )


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
