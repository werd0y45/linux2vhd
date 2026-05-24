"""VM runner abstractions for validation campaigns."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from linux_vhd_launcher.models import ValidationArtifact, VmRunnerConfig, VmRunnerStatus
from linux_vhd_launcher.system.runner import CommandRunner


class VmRunner:
    """VM campaign runner interface."""

    def check_status(self) -> VmRunnerStatus:
        """Return current runner status."""
        raise NotImplementedError

    def before_campaign(self) -> None:
        """Prepare campaign execution."""
        raise NotImplementedError

    def after_campaign(self) -> None:
        """Finalize campaign execution."""
        raise NotImplementedError

    def collect_artifacts(self, report_dir: Path) -> list[ValidationArtifact]:
        """Collect runner-related artifacts into report metadata."""
        raise NotImplementedError


@dataclass(slots=True)
class ManualVmRunner(VmRunner):
    """Manual runner: no automation, snapshot confirmation required by caller."""

    config: VmRunnerConfig
    snapshot_confirmed: bool = False

    def check_status(self) -> VmRunnerStatus:
        warnings: list[str] = []
        if self.config.require_snapshot and not self.snapshot_confirmed:
            warnings.append("Snapshot confirmation is required before mutation stages.")
        return VmRunnerStatus(
            runner="manual",
            vm_name=self.config.vm_name,
            snapshot_present=True if self.snapshot_confirmed else None,
            can_restore_snapshot=True if self.snapshot_confirmed else None,
            can_export_artifacts=True,
            warnings=warnings,
        )

    def before_campaign(self) -> None:
        if self.config.require_snapshot and not self.snapshot_confirmed:
            raise RuntimeError(
                "Manual VM runner requires explicit snapshot confirmation. "
                "Pass --confirm-vm-snapshot."
            )

    def after_campaign(self) -> None:
        return None

    def collect_artifacts(self, report_dir: Path) -> list[ValidationArtifact]:
        note = report_dir / "vm_runner_manual.txt"
        note.write_text(
            "Manual VM runner used; snapshot handling confirmed by operator.\n",
            encoding="utf-8",
        )
        return [
            ValidationArtifact(
                kind="vm_runner",
                path=note,
                sha256=None,
                description="Manual VM runner metadata",
            )
        ]


@dataclass(slots=True)
class ExternalVmRunner(VmRunner):
    """External command-hook runner with dry-run default behavior."""

    config: VmRunnerConfig
    before_hook: list[str] | None = None
    after_hook: list[str] | None = None
    collect_hook: list[str] | None = None
    runner_factory: Callable[[bool], CommandRunner] = field(
        default=lambda dry_run: CommandRunner(dry_run=dry_run)
    )

    def check_status(self) -> VmRunnerStatus:
        warnings: list[str] = []
        if not self.before_hook and not self.after_hook and not self.collect_hook:
            warnings.append("No external hooks configured; runner operates as no-op.")
        if not self.config.allow_mutation:
            warnings.append("Mutation is disabled; hooks should be dry-run/safe only.")
        return VmRunnerStatus(
            runner="external",
            vm_name=self.config.vm_name,
            snapshot_present=None,
            can_restore_snapshot=None,
            can_export_artifacts=self.collect_hook is not None,
            warnings=warnings,
        )

    def before_campaign(self) -> None:
        self._run_hook(self.before_hook)

    def after_campaign(self) -> None:
        self._run_hook(self.after_hook)

    def collect_artifacts(self, report_dir: Path) -> list[ValidationArtifact]:
        artifacts: list[ValidationArtifact] = []
        if self.collect_hook:
            self._run_hook(self.collect_hook)
            marker = report_dir / "vm_runner_external_collect.txt"
            marker.write_text("External collect hook executed.\n", encoding="utf-8")
            artifacts.append(
                ValidationArtifact(
                    kind="vm_runner",
                    path=marker,
                    sha256=None,
                    description="External VM runner collect hook marker",
                )
            )
        return artifacts

    def _run_hook(self, hook: Sequence[str] | None) -> None:
        if not hook:
            return
        # External runner is intentionally dry-run by default.
        dry_run = not self.config.allow_mutation
        self.runner_factory(dry_run).run(hook, elevated_required=False, check=False)


@dataclass(slots=True)
class HyperVVmRunner(VmRunner):
    """Planning/probe skeleton for Hyper-V runner."""

    config: VmRunnerConfig
    which: Callable[[str], str | None]

    def check_status(self) -> VmRunnerStatus:
        powershell_available = self.which("powershell") is not None or self.which("pwsh") is not None
        warnings: list[str] = [
            "Hyper-V runner is planning/probe skeleton in v0.5.",
            "Real checkpoint restore operations remain gated and are not auto-executed.",
        ]
        if not powershell_available:
            warnings.append("PowerShell is unavailable; Hyper-V probes are limited.")

        return VmRunnerStatus(
            runner="hyperv",
            vm_name=self.config.vm_name,
            snapshot_present=None,
            can_restore_snapshot=False,
            can_export_artifacts=False,
            warnings=warnings,
        )

    def before_campaign(self) -> None:
        return None

    def after_campaign(self) -> None:
        return None

    def collect_artifacts(self, report_dir: Path) -> list[ValidationArtifact]:
        note = report_dir / "vm_runner_hyperv_skeleton.txt"
        note.write_text(
            "Hyper-V runner skeleton used; no automatic checkpoint actions executed.\n",
            encoding="utf-8",
        )
        return [
            ValidationArtifact(
                kind="vm_runner",
                path=note,
                sha256=None,
                description="Hyper-V skeleton runner note",
            )
        ]


def build_vm_runner(
    config: VmRunnerConfig,
    *,
    snapshot_confirmed: bool,
    external_before_hook: list[str] | None = None,
    external_after_hook: list[str] | None = None,
    external_collect_hook: list[str] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> VmRunner:
    """Construct a runner implementation from config."""
    if config.runner == "manual":
        return ManualVmRunner(config=config, snapshot_confirmed=snapshot_confirmed)
    if config.runner == "external":
        return ExternalVmRunner(
            config=config,
            before_hook=external_before_hook,
            after_hook=external_after_hook,
            collect_hook=external_collect_hook,
        )
    return HyperVVmRunner(config=config, which=which or (lambda _: None))
