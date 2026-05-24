from __future__ import annotations

from pathlib import Path

from linux_vhd_launcher.models import OperationPlan, PlannedStep, VhdSpec
from linux_vhd_launcher.services.operation_planners import (
    BcdOperationPlanner,
    FullInstallPlanner,
    build_windows_lab_plan,
)
from linux_vhd_launcher.system.windows_bcd import BcdCommandBuilder


def test_planned_step_and_operation_plan_serialization() -> None:
    step = PlannedStep(
        id="s1",
        title="Step 1",
        command_preview=["echo", "ok"],
        description="desc",
        dangerous=False,
        rollback=None,
        docs_url="https://example.invalid",
        prerequisites=["pre-1"],
        expected_result="ok",
        rollback_action="none",
        verification_action="verify",
        risk_level="low",
    )
    plan = OperationPlan(
        title="Plan",
        target_platform="Windows",
        steps=[step],
        warnings=["warn"],
        dangerous=False,
        requires_admin=False,
        experimental=True,
    )

    payload = plan.to_dict()
    assert payload["title"] == "Plan"
    steps_raw = payload["steps"]
    assert isinstance(steps_raw, list)
    assert isinstance(steps_raw[0], dict)
    assert steps_raw[0]["id"] == "s1"
    assert steps_raw[0]["risk_level"] == "low"


def test_full_install_plan_uses_operation_plan_shape(tmp_path: Path) -> None:
    planner = FullInstallPlanner.from_defaults(BcdCommandBuilder())
    plan = planner.build(
        iso_path=tmp_path / "linux.iso",
        vhd_spec=VhdSpec(path=tmp_path / "linux.vhdx", size_gb=20, format="vhdx"),
        dry_run=True,
        bcd_backup_path=tmp_path / "backup.bcd",
    )

    assert isinstance(plan, OperationPlan)
    assert plan.dangerous is True
    assert any(step.id == "bcd-copy-current" for step in plan.steps)


def test_bcd_planner_warns_experimental(tmp_path: Path) -> None:
    planner = BcdOperationPlanner(BcdCommandBuilder())
    plan = planner.build(
        description="Linux",
        device="vhd=[C:]\\linux.vhdx",
        loader_path=r"\EFI\BOOT\BOOTX64.EFI",
        backup_path=tmp_path / "backup.bcd",
    )

    assert plan.experimental is True
    assert any("experimental" in warning.lower() for warning in plan.warnings)


def test_plan_windows_lab_contains_expected_steps() -> None:
    plan = build_windows_lab_plan()
    step_ids = [step.id for step in plan.steps]

    assert "lab-snapshot" in step_ids
    assert "lab-experimental-entry" in step_ids
    assert "lab-rollback-check" in step_ids


def test_operation_plan_steps_include_prerequisites_and_risk_levels(tmp_path: Path) -> None:
    planner = FullInstallPlanner.from_defaults(BcdCommandBuilder())
    plan = planner.build(
        iso_path=tmp_path / "linux.iso",
        vhd_spec=VhdSpec(path=tmp_path / "linux.vhdx", size_gb=20, format="vhdx"),
        dry_run=True,
        bcd_backup_path=tmp_path / "backup.bcd",
    )
    payload = plan.to_dict()
    steps_raw = payload["steps"]
    assert isinstance(steps_raw, list)
    first = steps_raw[0]
    assert isinstance(first, dict)
    assert "prerequisites" in first
    assert "risk_level" in first
    assert first["risk_level"] in {"low", "medium", "high", "critical"}


def test_dangerous_and_experimental_flags_preserved(tmp_path: Path) -> None:
    plan = build_windows_lab_plan()
    payload = plan.to_dict()
    assert payload["dangerous"] is True
    assert payload["experimental"] is True
