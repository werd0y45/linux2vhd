from __future__ import annotations

import json
from pathlib import Path

import pytest

from linux_vhd_launcher import cli
from linux_vhd_launcher.demo.live_vhd_demo import (
    DemoContext,
    build_payload,
    mark_boot_result,
    register_live,
    uninstall_live,
)
from linux_vhd_launcher.errors import UnsafeRealOperationError, UnsupportedPlatformError
from linux_vhd_launcher.models import LiveIsoInfo
from linux_vhd_launcher.services.grub_config import (
    GrubLiveIsoConfig,
    generate_ubuntu_loopback_grub_cfg,
)
from linux_vhd_launcher.services.live_boot_registration import (
    BcdBootMgrStrategy,
    BlockedUnsupportedStrategy,
    LiveRegistrationRequest,
    choose_registration_strategy,
)
from linux_vhd_launcher.services.live_payload import (
    build_live_vhd,
    build_live_vhd_layout,
    build_live_vhd_plan,
    inspect_live_iso,
)


def _make_fake_iso_tree(root: Path, *, name: str = "ubuntu-24.04-desktop-amd64.iso") -> Path:
    iso_dir = root / name
    (iso_dir / "EFI" / "BOOT").mkdir(parents=True)
    (iso_dir / "casper").mkdir(parents=True)
    (iso_dir / "EFI" / "BOOT" / "BOOTX64.EFI").write_bytes(b"efi")
    (iso_dir / "EFI" / "BOOT" / "shimx64.efi").write_bytes(b"shim")
    (iso_dir / "EFI" / "BOOT" / "grubx64.efi").write_bytes(b"grub")
    (iso_dir / "casper" / "vmlinuz").write_bytes(b"kernel")
    (iso_dir / "casper" / "initrd").write_bytes(b"initrd")
    return iso_dir


def _make_iso_info(path: Path) -> LiveIsoInfo:
    return LiveIsoInfo(
        iso_path=path,
        distro="Ubuntu",
        version="24.04",
        sha256="abcd",
        size_bytes=1024,
        has_efi_boot=True,
        has_shim=True,
        has_grub=True,
        has_casper_kernel=True,
        kernel_path="/casper/vmlinuz",
        initrd_path="/casper/initrd",
    )


def test_inspect_live_iso_directory_fixture(tmp_path: Path) -> None:
    iso_dir = _make_fake_iso_tree(tmp_path)
    info = inspect_live_iso(iso_dir)
    assert info.distro == "Ubuntu"
    assert info.version == "24.04"
    assert info.has_efi_boot is True
    assert info.has_shim is True
    assert info.has_grub is True
    assert info.has_casper_kernel is True
    assert info.kernel_path == "/casper/vmlinuz"
    assert info.initrd_path == "/casper/initrd"


def test_grub_cfg_generation() -> None:
    cfg = generate_ubuntu_loopback_grub_cfg(
        GrubLiveIsoConfig(
            iso_inside_path="/live/ubuntu.iso",
            kernel_path="/casper/vmlinuz",
            initrd_path="/casper/initrd",
        )
    )
    assert "loopback loop /live/ubuntu.iso" in cfg
    assert "linux (loop)/casper/vmlinuz" in cfg
    assert "initrd (loop)/casper/initrd" in cfg


def test_plan_live_vhd_contains_risks_and_rollbacks(tmp_path: Path) -> None:
    iso_dir = _make_fake_iso_tree(tmp_path)
    info = inspect_live_iso(iso_dir)
    layout = build_live_vhd_layout(iso_info=info, vhd_path=tmp_path / "x.vhdx", size_gb=12)
    plan = build_live_vhd_plan(iso=info, layout=layout)
    assert plan.experimental is True
    assert not plan.blockers
    assert all(step.risk_level in {"low", "medium", "high", "critical"} for step in plan.steps)
    assert all(step.rollback_action for step in plan.steps)


def test_build_vhd_dry_run_records_artifacts(tmp_path: Path) -> None:
    iso_dir = _make_fake_iso_tree(tmp_path)
    ctx = DemoContext(
        lab_dir=tmp_path / "lab",
        report_dir=tmp_path / "reports",
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )

    result = build_payload(
        context=ctx,
        iso_path=iso_dir,
        vhd_path=tmp_path / "lab" / "ubuntu-live.vhdx",
        size_gb=12,
    )
    assert result.status == "planned"
    assert (ctx.report_dir / "OperationPlan.json").exists()
    assert (ctx.report_dir / "LiveIsoInfo.json").exists()
    assert (ctx.report_dir / "LiveVhdBuildPlan.json").exists()
    assert (ctx.report_dir / "live_build_outcome.json").exists()


def test_build_live_vhd_real_refused_on_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    iso_info = _make_iso_info(tmp_path / "ubuntu.iso")
    layout = build_live_vhd_layout(iso_info=iso_info, vhd_path=tmp_path / "x.vhdx", size_gb=12)

    monkeypatch.setattr("linux_vhd_launcher.services.live_payload.is_windows_platform", lambda: False)

    with pytest.raises(UnsupportedPlatformError):
        build_live_vhd(
            iso=iso_info,
            layout=layout,
            lab_dir=tmp_path,
            report_dir=tmp_path / "reports",
            dry_run=False,
            execute_real_windows_ops=True,
            confirmation_token=True,
            confirm_vm_snapshot=True,
        )


def test_build_live_vhd_real_refused_on_windows_non_admin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iso_info = _make_iso_info(tmp_path / "ubuntu.iso")
    layout = build_live_vhd_layout(iso_info=iso_info, vhd_path=tmp_path / "x.vhdx", size_gb=12)

    monkeypatch.setattr("linux_vhd_launcher.services.live_payload.is_windows_platform", lambda: True)
    monkeypatch.setattr("linux_vhd_launcher.services.live_payload.is_admin", lambda: False)

    with pytest.raises(UnsafeRealOperationError, match="administrator privileges"):
        build_live_vhd(
            iso=iso_info,
            layout=layout,
            lab_dir=tmp_path,
            report_dir=tmp_path / "reports",
            dry_run=False,
            execute_real_windows_ops=True,
            confirmation_token=True,
            confirm_vm_snapshot=True,
        )


def test_build_live_vhd_real_requires_snapshot_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    iso_info = _make_iso_info(tmp_path / "ubuntu.iso")
    layout = build_live_vhd_layout(iso_info=iso_info, vhd_path=tmp_path / "x.vhdx", size_gb=12)

    monkeypatch.setattr("linux_vhd_launcher.services.live_payload.is_windows_platform", lambda: True)
    monkeypatch.setattr("linux_vhd_launcher.services.live_payload.is_admin", lambda: True)

    with pytest.raises(UnsafeRealOperationError, match="confirm-vm-snapshot"):
        build_live_vhd(
            iso=iso_info,
            layout=layout,
            lab_dir=tmp_path,
            report_dir=tmp_path / "reports",
            dry_run=False,
            execute_real_windows_ops=True,
            confirmation_token=True,
            confirm_vm_snapshot=False,
        )


def test_bcd_registration_refused_without_gate(tmp_path: Path) -> None:
    strategy = BcdBootMgrStrategy(allow_unconfirmed_direct_chain=True)
    request = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=tmp_path / "x.vhdx",
            size_gb=12,
        ),
        report_dir=tmp_path / "reports",
        lab_dir=tmp_path / "lab",
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=False,
    )

    with pytest.raises(UnsafeRealOperationError, match="confirm-vm-snapshot"):
        strategy.register(request)


def test_bcd_strategy_blocked_when_unsupported(tmp_path: Path) -> None:
    strategy = choose_registration_strategy("auto")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=tmp_path / "x.vhdx",
            size_gb=12,
        ),
        report_dir=tmp_path,
        lab_dir=tmp_path,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    out = strategy.register(req)
    assert out.status == "registration_blocked"
    assert out.blockers


def test_register_live_blocked_writes_artifacts(tmp_path: Path) -> None:
    ctx = DemoContext(
        lab_dir=tmp_path / "lab",
        report_dir=tmp_path / "reports",
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    out = register_live(
        context=ctx,
        vhd_path=tmp_path / "lab" / "ubuntu-live.vhdx",
        strategy="blocked",
    )
    assert out.status == "registration_blocked"
    assert (ctx.report_dir / "live_registration_outcome.json").exists()
    assert (ctx.report_dir / "demo_status.json").exists()


def test_uninstall_refuses_unknown_guid(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True)
    (report_dir / "live_registration_manifest.json").write_text(
        json.dumps({"guid": "{11111111-1111-1111-1111-111111111111}"}),
        encoding="utf-8",
    )
    ctx = DemoContext(
        lab_dir=tmp_path / "lab",
        report_dir=report_dir,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    with pytest.raises(UnsafeRealOperationError, match="unknown GUID"):
        uninstall_live(
            context=ctx,
            guid="{22222222-2222-2222-2222-222222222222}",
            delete_vhd=False,
            vhd_path=None,
        )


def test_mark_boot_result_creates_manual_artifact(tmp_path: Path) -> None:
    out = mark_boot_result(report_dir=tmp_path, result="booted", notes="ok")
    assert out.status == "bootability_confirmed_manual"
    assert (tmp_path / "manual_boot_result.json").exists()


def test_cli_demo_help(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    with pytest.raises(SystemExit):
        cli.main(["demo", "--help"])
    output = capsys.readouterr().out
    assert "inspect-iso" in output
    assert "live" in output


def test_cli_demo_commands_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    iso_dir = _make_fake_iso_tree(tmp_path)
    lab_dir = tmp_path / "lab"
    report_dir = tmp_path / "reports"
    vhd_path = lab_dir / "ubuntu-live.vhdx"

    inspect_code = cli.main(["demo", "inspect-iso", "--iso", str(iso_dir), "--json"])
    plan_code = cli.main(
        [
            "demo",
            "live",
            "plan",
            "--iso",
            str(iso_dir),
            "--vhd",
            str(vhd_path),
            "--size-gb",
            "12",
            "--lab-dir",
            str(lab_dir),
            "--json",
        ]
    )
    build_code = cli.main(
        [
            "demo",
            "live",
            "build-vhd",
            "--iso",
            str(iso_dir),
            "--vhd",
            str(vhd_path),
            "--size-gb",
            "12",
            "--lab-dir",
            str(lab_dir),
            "--report-dir",
            str(report_dir),
            "--json",
        ]
    )
    register_code = cli.main(
        [
            "demo",
            "live",
            "register-bcd",
            "--vhd",
            str(vhd_path),
            "--lab-dir",
            str(lab_dir),
            "--report-dir",
            str(report_dir),
            "--strategy",
            "auto",
            "--json",
        ]
    )

    assert inspect_code == 0
    assert plan_code == 0
    assert build_code == 0
    assert register_code == 2


def test_blocked_strategy_direct() -> None:
    strategy = BlockedUnsupportedStrategy(reason="blocked")
    out = strategy.register(
        LiveRegistrationRequest(
            layout=build_live_vhd_layout(
                iso_info=_make_iso_info(Path("x.iso")),
                vhd_path=Path("x.vhdx"),
                size_gb=12,
            ),
            report_dir=Path("."),
            lab_dir=Path("."),
            dry_run=True,
            execute_real_windows_ops=False,
            confirmation_token=False,
            confirm_vm_snapshot=False,
        )
    )
    assert out.status == "registration_blocked"
