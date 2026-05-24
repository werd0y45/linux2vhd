from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher.models import VmRunnerConfig
from linux_vhd_launcher.vm_runners import (
    ExternalVmRunner,
    HyperVVmRunner,
    ManualVmRunner,
    build_vm_runner,
)


class DummyCommandRunner:
    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.commands: list[list[str]] = []

    def run(self, command, *, elevated_required: bool, check: bool):  # noqa: ANN001
        self.commands.append(list(command))
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()


def _config(tmp_path: Path, runner: str = "manual") -> VmRunnerConfig:
    return VmRunnerConfig(
        runner=runner,  # type: ignore[arg-type]
        vm_name="vm1",
        snapshot_name="snap1",
        working_dir=tmp_path,
        require_snapshot=True,
        allow_mutation=False,
    )


def test_manual_vm_runner_requires_snapshot_confirmation(tmp_path: Path) -> None:
    runner = ManualVmRunner(config=_config(tmp_path), snapshot_confirmed=False)
    with pytest.raises(RuntimeError):
        runner.before_campaign()


def test_manual_vm_runner_status_with_confirmation(tmp_path: Path) -> None:
    runner = ManualVmRunner(config=_config(tmp_path), snapshot_confirmed=True)
    status = runner.check_status()
    assert status.snapshot_present is True
    assert not status.warnings


def test_external_vm_runner_executes_hooks(tmp_path: Path) -> None:
    captured: list[DummyCommandRunner] = []

    def _factory(dry_run: bool):
        runner = DummyCommandRunner(dry_run=dry_run)
        captured.append(runner)
        return runner

    runner = ExternalVmRunner(
        config=_config(tmp_path, runner="external"),
        before_hook=["echo", "before"],
        after_hook=["echo", "after"],
        collect_hook=["echo", "collect"],
        runner_factory=_factory,
    )
    runner.before_campaign()
    runner.after_campaign()
    artifacts = runner.collect_artifacts(tmp_path)

    assert artifacts
    assert len(captured) == 3
    assert all(obj.dry_run for obj in captured)


def test_hyperv_runner_is_skeleton(tmp_path: Path) -> None:
    runner = HyperVVmRunner(
        config=_config(tmp_path, runner="hyperv"),
        which=lambda _: None,
    )
    status = runner.check_status()
    assert status.runner == "hyperv"
    assert status.can_restore_snapshot is False
    assert status.warnings


def test_build_vm_runner_manual(tmp_path: Path) -> None:
    runner = build_vm_runner(
        _config(tmp_path),
        snapshot_confirmed=True,
        which=lambda _: None,
    )
    assert isinstance(runner, ManualVmRunner)
