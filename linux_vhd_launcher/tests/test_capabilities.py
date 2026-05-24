from __future__ import annotations

from linux_vhd_launcher.capabilities import (
    BcdCapabilityScanner,
    EnvironmentCapabilityScanner,
    FakeCapabilityScanner,
    PowerShellCapabilityScanner,
    VhdCapabilityScanner,
    VirtdiskCapabilityScanner,
    run_capability_scanners,
)
from linux_vhd_launcher.models import BackendCapability, ProbeResult


def _which_map(values: dict[str, str | None]):
    def _which(name: str) -> str | None:
        return values.get(name)

    return _which


def test_bcd_capability_scanner_reports_missing_tools() -> None:
    scanner = BcdCapabilityScanner(which=_which_map({}))
    capabilities, probes = scanner.scan()

    assert {c.capability for c in capabilities} == {"bcdedit", "bcdboot"}
    assert any(probe.id == "probe.bcdedit.available" and probe.status == "fail" for probe in probes)


def test_powershell_capability_scanner_reports_shell_presence() -> None:
    scanner = PowerShellCapabilityScanner(which=_which_map({"powershell": "powershell"}))
    capabilities, probes = scanner.scan()

    assert any(c.capability == "powershell" and c.status == "available" for c in capabilities)
    assert probes[0].status == "pass"


def test_virtdisk_scanner_non_windows_is_not_applicable() -> None:
    scanner = VirtdiskCapabilityScanner(is_windows=lambda: False)
    capabilities, probes = scanner.scan()

    assert capabilities[0].status == "blocked"
    assert probes[0].status == "not_applicable"


def test_environment_scanner_uses_injected_platform_checks() -> None:
    scanner = EnvironmentCapabilityScanner(is_windows=lambda: False, is_admin_fn=lambda: False)
    capabilities, probes = scanner.scan()

    assert any(c.capability == "windows-platform" and c.status == "blocked" for c in capabilities)
    assert any(p.id == "probe.platform.admin" and p.status == "warning" for p in probes)


def test_run_capability_scanners_with_fake_scanner() -> None:
    fake = FakeCapabilityScanner(
        capabilities=[
            BackendCapability(
                backend="fake",
                capability="x",
                status="available",
                reason=None,
                docs_url=None,
            )
        ],
        probes=[
            ProbeResult(
                id="fake.probe",
                name="fake",
                status="pass",
                value=True,
                details=None,
                source="tests",
                command_preview=None,
            )
        ],
    )
    capabilities, probes = run_capability_scanners(scanners=[fake])

    assert len(capabilities) == 1
    assert capabilities[0].backend == "fake"
    assert probes[0].id == "fake.probe"


def test_vhd_scanner_detects_diskpart_missing() -> None:
    scanner = VhdCapabilityScanner(which=_which_map({}))
    capabilities, probes = scanner.scan()
    assert capabilities[0].capability == "diskpart"
    assert probes[0].status == "fail"
