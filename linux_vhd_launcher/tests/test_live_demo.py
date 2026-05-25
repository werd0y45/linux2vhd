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
    LiveRegistrationOutcome,
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
    (tmp_path / "reports").mkdir()
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
    (tmp_path / "lab").mkdir(parents=True)
    (tmp_path / "reports").mkdir(parents=True)
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


def test_register_bcd_experimental_refuses_on_linux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report_dir = tmp_path / "reports"
    lab_dir = tmp_path / "lab"
    report_dir.mkdir()
    lab_dir.mkdir()
    strategy = choose_registration_strategy("bootmgr-experimental-vhd")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=lab_dir / "ubuntu-live.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
        allow_known_failed_strategy=True,
    )
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_windows_platform", lambda: False)
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_admin", lambda: True)
    with pytest.raises(UnsupportedPlatformError):
        strategy.register(req)


def test_register_bcd_experimental_refuses_on_non_admin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_dir = tmp_path / "reports"
    lab_dir = tmp_path / "lab"
    report_dir.mkdir()
    lab_dir.mkdir()
    strategy = choose_registration_strategy("bootmgr-experimental-vhd")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=lab_dir / "ubuntu-live.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
        allow_known_failed_strategy=True,
    )
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_windows_platform", lambda: True)
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_admin", lambda: False)
    with pytest.raises(UnsafeRealOperationError, match="administrator rights"):
        strategy.register(req)


def test_register_bcd_experimental_requires_snapshot(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    lab_dir = tmp_path / "lab"
    report_dir.mkdir()
    lab_dir.mkdir()
    strategy = choose_registration_strategy("bootmgr-experimental-vhd")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=lab_dir / "ubuntu-live.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=False,
        allow_known_failed_strategy=True,
    )
    with pytest.raises(UnsafeRealOperationError, match="confirm-vm-snapshot"):
        strategy.register(req)


def test_register_bcd_experimental_known_failed_blocked_by_default(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    lab_dir = tmp_path / "lab"
    report_dir.mkdir()
    lab_dir.mkdir()
    strategy = choose_registration_strategy("bootmgr-experimental-vhd")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=lab_dir / "ubuntu-live.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=lab_dir,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
        allow_known_failed_strategy=False,
    )
    out = strategy.register(req)
    assert out.status == "registration_blocked"
    assert out.known_failed_strategy == "copied-current-osloader-vhd"


def test_register_bcd_experimental_dry_run_includes_exact_plan_when_allowed(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    lab_dir = tmp_path / "lab"
    report_dir.mkdir()
    lab_dir.mkdir()
    strategy = choose_registration_strategy("bootmgr-experimental-vhd")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=lab_dir / "ubuntu-live.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=lab_dir,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
        allow_known_failed_strategy=True,
    )
    out = strategy.register(req)
    assert out.status == "planned"
    assert out.planned_commands
    assert ["bcdedit", "/enum", "all"] in out.planned_commands
    assert ["bcdedit", "/enum", "firmware"] in out.planned_commands
    assert ["bcdedit", "/displayorder", "{GUID}", "/addlast"] in out.planned_commands
    assert all("{bootmgr}" not in " ".join(command) for command in out.planned_commands)


def test_register_bcd_experimental_real_records_commands_with_fake_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_dir = tmp_path / "reports"
    lab_dir = tmp_path / "lab"
    report_dir.mkdir()
    lab_dir.mkdir()

    class FakeRunner:
        def __init__(self) -> None:
            self.commands: list[list[str]] = []

        def run(
            self,
            command: list[str],
            *,
            elevated_required: bool = False,
            check: bool = True,
        ):
            del elevated_required
            del check
            self.commands.append(command)
            stdout = "ok"
            if command[:3] == ["bcdedit", "/copy", "{current}"]:
                stdout = "The entry was successfully copied to {11111111-1111-1111-1111-111111111111}."
            from linux_vhd_launcher.system.runner import CommandResult

            return CommandResult(command=tuple(command), returncode=0, stdout=stdout, stderr="")

    fake_runner = FakeRunner()
    strategy = BcdBootMgrStrategy(
        name="bootmgr-experimental-vhd",
        allow_unconfirmed_direct_chain=True,
        known_failed_strategy_id="copied-current-osloader-vhd",
        runner_factory=lambda: fake_runner,  # type: ignore[arg-type]
    )
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=lab_dir / "ubuntu-live.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
        allow_known_failed_strategy=True,
    )
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_windows_platform", lambda: True)
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_admin", lambda: True)
    monkeypatch.setattr(
        "linux_vhd_launcher.services.live_boot_registration.RealWindowsOpsGate.assert_allowed",
        lambda self, **kwargs: None,
    )
    out = strategy.register(req)
    assert out.status == "registration_experimental_done_but_boot_failed"
    assert out.created_guid == "{11111111-1111-1111-1111-111111111111}"
    assert out.known_failed_strategy == "copied-current-osloader-vhd"
    assert out.unregister_command == ["bcdedit", "/delete", out.created_guid, "/f"]
    recorded = [" ".join(item.command) for item in out.executed_commands]
    assert any("bcdedit /displayorder {11111111-1111-1111-1111-111111111111} /addlast" in c for c in recorded)
    assert all("{bootmgr}" not in c for c in recorded)
    assert all("/default" not in c for c in recorded)


def test_register_bcd_experimental_failure_after_copy_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_dir = tmp_path / "reports"
    lab_dir = tmp_path / "lab"
    report_dir.mkdir()
    lab_dir.mkdir()

    class FakeRunner:
        def run(
            self,
            command: list[str],
            *,
            elevated_required: bool = False,
            check: bool = True,
        ):
            del elevated_required
            del check
            from linux_vhd_launcher.system.runner import CommandResult

            if command[:3] == ["bcdedit", "/copy", "{current}"]:
                return CommandResult(
                    command=tuple(command),
                    returncode=0,
                    stdout="copied {22222222-2222-2222-2222-222222222222}",
                    stderr="",
                )
            if command[:4] == ["bcdedit", "/set", "{22222222-2222-2222-2222-222222222222}", "device"]:
                return CommandResult(command=tuple(command), returncode=1, stdout="", stderr="set failed")
            return CommandResult(command=tuple(command), returncode=0, stdout="ok", stderr="")

    strategy = BcdBootMgrStrategy(
        name="bootmgr-experimental-vhd",
        allow_unconfirmed_direct_chain=True,
        runner_factory=lambda: FakeRunner(),  # type: ignore[arg-type]
    )
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=lab_dir / "ubuntu-live.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
        allow_known_failed_strategy=True,
    )
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_windows_platform", lambda: True)
    monkeypatch.setattr("linux_vhd_launcher.services.live_boot_registration.is_admin", lambda: True)
    monkeypatch.setattr(
        "linux_vhd_launcher.services.live_boot_registration.RealWindowsOpsGate.assert_allowed",
        lambda self, **kwargs: None,
    )
    out: LiveRegistrationOutcome = strategy.register(req)
    assert out.status == "registration_failed"
    assert any("bcdedit /delete {22222222-2222-2222-2222-222222222222} /f" == " ".join(item.command) for item in out.executed_commands)
    assert out.rollback_actions == ["bcdedit /delete {22222222-2222-2222-2222-222222222222} /f"]


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

    with pytest.raises(SystemExit):
        cli.main(["demo", "live", "--help"])
    live_output = capsys.readouterr().out
    assert "unregister-bcd" in live_output
    with pytest.raises(SystemExit):
        cli.main(["demo", "live", "register-bcd", "--help"])
    register_help = capsys.readouterr().out
    assert "firmware-efi-staged" in register_help


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


def test_cli_known_failed_strategy_requires_allow_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    lab_dir = tmp_path / "lab"
    report_dir = tmp_path / "reports"
    lab_dir.mkdir()
    report_dir.mkdir()
    vhd_path = lab_dir / "ubuntu-live.vhdx"

    blocked = cli.main(
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
            "bootmgr-experimental-vhd",
            "--json",
        ]
    )
    allowed = cli.main(
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
            "bootmgr-experimental-vhd",
            "--allow-known-failed-strategy",
            "--json",
        ]
    )
    assert blocked == 2
    assert allowed == 0


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


def test_firmware_efi_staged_strategy_dry_run_only(tmp_path: Path) -> None:
    strategy = choose_registration_strategy("firmware-efi-staged")
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
    assert out.status == "planned"
    assert out.planned_commands
    assert all("/copy" not in " ".join(command) for command in out.planned_commands)
    assert all("{bootmgr}" not in " ".join(command) for command in out.planned_commands)
    assert all("/default" not in " ".join(command) for command in out.planned_commands)
    assert out.esp_staging_plan is not None
    assert out.esp_staging_plan.rollback_steps
    assert out.esp_staging_plan.requires_esp_write is True

    req_real = LiveRegistrationRequest(
        layout=req.layout,
        report_dir=req.report_dir,
        lab_dir=req.lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
    )
    out_real = strategy.register(req_real)
    assert out_real.status == "registration_blocked"
    assert "allow-esp-write" in (out_real.blockers[0] if out_real.blockers else "")

    req_real_flags = LiveRegistrationRequest(
        layout=req.layout,
        report_dir=req.report_dir,
        lab_dir=req.lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
        allow_esp_write=True,
        allow_firmware_entry=True,
        allow_secure_boot_experiment=True,
    )
    out_real_flags = strategy.register(req_real_flags)
    assert out_real_flags.status == "registration_blocked"
    assert any("real mode remains blocked" in blocker for blocker in out_real_flags.blockers)


def test_firmware_efi_bootapp_probe_requires_probe_report(tmp_path: Path) -> None:
    strategy = choose_registration_strategy("firmware-efi-bootapp-probe")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=tmp_path / "x.vhdx",
            size_gb=12,
        ),
        report_dir=tmp_path / "reports",
        lab_dir=tmp_path,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    req.report_dir.mkdir(parents=True, exist_ok=True)
    out = strategy.register(req)
    assert out.status == "registration_blocked"
    assert "probe-bootapp-elements" in (out.blockers[0] if out.blockers else "")


def test_firmware_efi_bootapp_probe_dry_run_plan(tmp_path: Path) -> None:
    strategy = choose_registration_strategy("firmware-efi-bootapp-probe")
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "bcd_bootapp_elements_probe.json").write_text(
        json.dumps(
            {
                "report": {
                    "create_supported": True,
                    "element_probes": [
                        {"element": "device", "value": "partition=C:", "supported": True},
                        {
                            "element": "path",
                            "value": "\\EFI\\LinuxVHDLauncher\\ubuntu-live\\BOOTX64.EFI",
                            "supported": True,
                        },
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=tmp_path / "x.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=tmp_path,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    out = strategy.register(req)
    assert out.status == "planned"
    assert out.planned_commands
    assert any("/application" in " ".join(command) and "bootapp" in " ".join(command) for command in out.planned_commands)
    assert all("/copy {current}" not in " ".join(command) for command in out.planned_commands)
    assert all("{bootmgr}" not in " ".join(command) for command in out.planned_commands)

    req_real = LiveRegistrationRequest(
        layout=req.layout,
        report_dir=req.report_dir,
        lab_dir=req.lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
    )
    out_real = strategy.register(req_real)
    assert out_real.status == "registration_blocked"
    assert any("real mode remains blocked" in blocker for blocker in out_real.blockers)


def test_firmware_efi_bootapp_system_dry_run_strategy_available(tmp_path: Path) -> None:
    strategy = choose_registration_strategy("firmware-efi-bootapp-system-dry-run")
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "bcd_bootapp_elements_probe.json").write_text(
        json.dumps(
            {
                "report": {
                    "create_supported": True,
                    "element_probes": [
                        {"element": "device", "value": "partition=C:", "supported": True},
                        {
                            "element": "path",
                            "value": "\\EFI\\LinuxVHDLauncher\\ubuntu-live\\BOOTX64.EFI",
                            "supported": True,
                        },
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=tmp_path / "x.vhdx",
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=tmp_path,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    out = strategy.register(req)
    assert out.status == "planned"
    assert ["bcdedit", "/set", "{GUID}", "device", "partition=S:"] in out.planned_commands


def test_bootapp_vhd_system_dry_run_strategy_requires_probe_report(tmp_path: Path) -> None:
    strategy = choose_registration_strategy("bootapp-vhd-system-dry-run")
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=tmp_path / "x.vhdx",
            size_gb=12,
        ),
        report_dir=tmp_path / "reports",
        lab_dir=tmp_path,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    req.report_dir.mkdir(parents=True, exist_ok=True)
    out = strategy.register(req)
    assert out.status == "registration_blocked"
    assert "probe-bootapp-vhd-device" in (out.blockers[0] if out.blockers else "")


def test_bootapp_vhd_system_dry_run_plan_and_blocked_real(tmp_path: Path) -> None:
    strategy = choose_registration_strategy("bootapp-vhd-system-dry-run")
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    vhd_path = Path("C:/LVHLab/ubuntu-live.vhdx")
    (report_dir / "bcd_bootapp_vhd_device_probe.json").write_text(
        json.dumps(
            {
                "report": {
                    "vhd_path": str(vhd_path),
                    "create_supported": True,
                    "element_probes": [
                        {
                            "element": "device",
                            "value": "vhd=[C:]\\LVHLab\\ubuntu-live.vhdx",
                            "supported": True,
                        },
                        {"element": "path", "value": "\\EFI\\BOOT\\BOOTX64.EFI", "supported": True},
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    req = LiveRegistrationRequest(
        layout=build_live_vhd_layout(
            iso_info=_make_iso_info(tmp_path / "ubuntu.iso"),
            vhd_path=vhd_path,
            size_gb=12,
        ),
        report_dir=report_dir,
        lab_dir=tmp_path,
        dry_run=True,
        execute_real_windows_ops=False,
        confirmation_token=False,
        confirm_vm_snapshot=False,
    )
    out = strategy.register(req)
    assert out.status == "planned"
    assert ["bcdedit", "/set", "{GUID}", "device", "vhd=[C:]\\LVHLab\\ubuntu-live.vhdx"] in out.planned_commands
    assert ["bcdedit", "/set", "{GUID}", "path", "\\EFI\\BOOT\\BOOTX64.EFI"] in out.planned_commands
    assert all("/copy {current}" not in " ".join(command) for command in out.planned_commands)
    assert all("{bootmgr}" not in " ".join(command) for command in out.planned_commands)

    req_real = LiveRegistrationRequest(
        layout=req.layout,
        report_dir=req.report_dir,
        lab_dir=req.lab_dir,
        dry_run=False,
        execute_real_windows_ops=True,
        confirmation_token=True,
        confirm_vm_snapshot=True,
    )
    out_real = strategy.register(req_real)
    assert out_real.status == "registration_blocked"
    assert any("real mode remains blocked" in blocker for blocker in out_real.blockers)


def test_docs_bcd_registration_mentions_known_failed_analysis() -> None:
    content = Path("docs/BCD_LIVE_REGISTRATION.md").read_text(encoding="utf-8")
    assert "known-failed" in content.lower() or "known failed" in content.lower()
    assert "copied" in content.lower()


def test_cli_stage_esp_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINUX_VHD_LAUNCHER_HOME", str(tmp_path / ".cfg"))
    lab_dir = tmp_path / "lab"
    report_dir = tmp_path / "reports"
    lab_dir.mkdir()
    report_dir.mkdir()
    vhd_path = lab_dir / "ubuntu-live.vhdx"

    plan_code = cli.main(
        [
            "demo",
            "live",
            "stage-esp-plan",
            "--vhd",
            str(vhd_path),
            "--lab-dir",
            str(lab_dir),
            "--report-dir",
            str(report_dir),
            "--json",
        ]
    )
    apply_code = cli.main(
        [
            "demo",
            "live",
            "stage-esp-apply",
            "--vhd",
            str(vhd_path),
            "--lab-dir",
            str(lab_dir),
            "--report-dir",
            str(report_dir),
            "--no-dry-run",
            "--json",
        ]
    )
    cleanup_code = cli.main(
        [
            "demo",
            "live",
            "stage-esp-cleanup",
            "--lab-dir",
            str(lab_dir),
            "--report-dir",
            str(report_dir),
            "--json",
        ]
    )
    assert plan_code == 0
    assert apply_code == 2
    assert cleanup_code == 0
