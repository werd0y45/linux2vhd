"""Offline BCD application-type capability probe helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from linux_vhd_launcher.errors import UnsupportedPlatformError
from linux_vhd_launcher.models import (
    BcdApplicationTypeProbe,
    BcdBootappElementProbeReport,
    BcdElementSetProbe,
    BcdProbeReport,
)
from linux_vhd_launcher.system.runner import CommandRunner
from linux_vhd_launcher.system.windows_privileges import is_windows_platform

_GUID_RE = re.compile(r"\{[0-9a-fA-F\-]+\}")
_BASE_APPLICATION_TYPES = ("osloader", "bootsector", "bootapp")
_BOOTAPP_ELEMENTS_LABEL = "LVH Probe BOOTAPP ELEMENTS"
_BOOTAPP_PATH_VALUE = "\\EFI\\LinuxVHDLauncher\\ubuntu-live\\BOOTX64.EFI"


@dataclass(slots=True)
class BcdProbeOutcome:
    """Execution output with report artifact paths."""

    report: BcdProbeReport
    report_path: Path
    enum_stderr_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "report": self.report.to_dict(),
            "report_path": str(self.report_path),
            "enum_stderr_path": str(self.enum_stderr_path),
        }


@dataclass(slots=True)
class BcdBootappElementProbeOutcome:
    """Execution output with report artifact paths for bootapp element probe."""

    report: BcdBootappElementProbeReport
    report_path: Path
    enum_stderr_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "report": self.report.to_dict(),
            "report_path": str(self.report_path),
            "enum_stderr_path": str(self.enum_stderr_path),
        }


def probe_bcd_application_types(
    *,
    lab_dir: Path,
    report_dir: Path,
    runner: CommandRunner | None = None,
) -> BcdProbeOutcome:
    """Probe BCDEdit /application support in an offline store only."""
    if not is_windows_platform():
        raise UnsupportedPlatformError(
            "demo bcd probe-application-types is supported only on Windows"
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = lab_dir / "bcd_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    store_path = probe_dir / "bcd_probe.bcd"
    enum_output_path = report_dir / "bcd_probe_enum_all_v.txt"
    enum_stderr_path = report_dir / "bcd_probe_enum_all_v.stderr.txt"
    report_path = report_dir / "bcd_application_type_probe.json"

    command_runner = runner or CommandRunner(dry_run=False)

    createstore = command_runner.run(
        ["bcdedit", "/createstore", str(store_path)],
        elevated_required=False,
        check=False,
    )

    probes: list[BcdApplicationTypeProbe] = []
    blocked_reason: str | None = None

    if createstore.returncode != 0:
        blocked_reason = (
            "Failed to create offline BCD store; probe matrix not executed. "
            f"stdout={createstore.stdout.strip()} stderr={createstore.stderr.strip()}"
        )
    else:
        for application_type in _probe_types_from_help(command_runner):
            command = [
                "bcdedit",
                "/store",
                str(store_path),
                "/create",
                "/d",
                f"LVH Probe {application_type.upper()}",
                "/application",
                application_type,
            ]
            result = command_runner.run(command, elevated_required=False, check=False)
            guid = _extract_guid(result.stdout)
            supported = result.returncode == 0 and guid is not None
            notes: str | None = None
            if result.returncode == 0 and guid is None:
                notes = "Command succeeded but GUID was not parsed from output."
            if result.returncode != 0:
                notes = "Application type rejected by bcdedit in offline store."
            probes.append(
                BcdApplicationTypeProbe(
                    application_type=application_type,
                    supported=supported,
                    guid=guid,
                    command=command,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    notes=notes,
                )
            )

    enum_result = command_runner.run(
        ["bcdedit", "/store", str(store_path), "/enum", "all", "/v"],
        elevated_required=False,
        check=False,
    )
    enum_output_path.write_text(enum_result.stdout, encoding="utf-8")
    enum_stderr_path.write_text(enum_result.stderr, encoding="utf-8")

    supported_types = [item.application_type for item in probes if item.supported]
    report = BcdProbeReport(
        store_path=store_path,
        probes=probes,
        enum_output_path=enum_output_path,
        supported_types=supported_types,
        blocked_reason=blocked_reason,
    )

    payload = {
        "report": report.to_dict(),
        "createstore": {
            "command": list(createstore.command),
            "returncode": createstore.returncode,
            "stdout": createstore.stdout,
            "stderr": createstore.stderr,
        },
        "enum": {
            "command": list(enum_result.command),
            "returncode": enum_result.returncode,
            "stdout_path": str(enum_output_path),
            "stderr_path": str(enum_stderr_path),
        },
        "safety": {
            "uses_offline_store_only": True,
            "system_store_mutation_attempted": False,
            "notes": [
                "All mutating create commands include /store <offline-store-path>.",
                "No command targets {bootmgr}, {fwbootmgr}, or system displayorder.",
            ],
        },
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return BcdProbeOutcome(
        report=report,
        report_path=report_path,
        enum_stderr_path=enum_stderr_path,
    )


def probe_bcd_bootapp_elements(
    *,
    lab_dir: Path,
    report_dir: Path,
    runner: CommandRunner | None = None,
) -> BcdBootappElementProbeOutcome:
    """Probe BOOTAPP create and set-element support in an offline store only."""
    if not is_windows_platform():
        raise UnsupportedPlatformError(
            "demo bcd probe-bootapp-elements is supported only on Windows"
        )

    report_dir.mkdir(parents=True, exist_ok=True)
    probe_dir = lab_dir / "bcd_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)

    store_path = probe_dir / "bootapp_elements_probe.bcd"
    enum_output_path = report_dir / "bcd_bootapp_elements_enum_all_v.txt"
    enum_stderr_path = report_dir / "bcd_bootapp_elements_enum_all_v.stderr.txt"
    report_path = report_dir / "bcd_bootapp_elements_probe.json"

    command_runner = runner or CommandRunner(dry_run=False)
    warnings: list[str] = []
    blockers: list[str] = []

    createstore = command_runner.run(
        ["bcdedit", "/createstore", str(store_path)],
        elevated_required=False,
        check=False,
    )

    bootapp_guid: str | None = None
    create_supported = False
    create_command = [
        "bcdedit",
        "/store",
        str(store_path),
        "/create",
        "/d",
        _BOOTAPP_ELEMENTS_LABEL,
        "/application",
        "bootapp",
    ]
    create_result = command_runner.run(create_command, elevated_required=False, check=False)
    if createstore.returncode != 0:
        blockers.append(
            "Failed to create offline BCD store for bootapp element probe."
        )
    else:
        bootapp_guid = _extract_guid(create_result.stdout)
        create_supported = create_result.returncode == 0 and bootapp_guid is not None
        if create_result.returncode != 0:
            blockers.append("Offline /create /application bootapp command was rejected.")
        elif bootapp_guid is None:
            blockers.append(
                "bootapp /create command succeeded but GUID was not parsed from output."
            )

    element_probes: list[BcdElementSetProbe] = []
    if create_supported and bootapp_guid is not None:
        for element, value in (
            ("device", "partition=C:"),
            ("path", _BOOTAPP_PATH_VALUE),
            ("description", _BOOTAPP_ELEMENTS_LABEL),
        ):
            command = [
                "bcdedit",
                "/store",
                str(store_path),
                "/set",
                bootapp_guid,
                element,
                value,
            ]
            result = command_runner.run(command, elevated_required=False, check=False)
            element_probes.append(
                BcdElementSetProbe(
                    element=element,
                    value=value,
                    supported=result.returncode == 0,
                    command=command,
                    returncode=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    notes=(
                        None
                        if result.returncode == 0
                        else "Element rejected by bcdedit in offline BOOTAPP probe."
                    ),
                )
            )
    else:
        warnings.append(
            "Skipping element /set probes because BOOTAPP entry creation was not confirmed."
        )

    warnings.append(
        "Optional variants were intentionally skipped: `device boot` and "
        "`device partition=\\Device\\HarddiskVolumeX`."
    )
    warnings.append(
        "Syntactic acceptance in offline store is not evidence of runtime bootability."
    )

    enum_result = command_runner.run(
        ["bcdedit", "/store", str(store_path), "/enum", "all", "/v"],
        elevated_required=False,
        check=False,
    )
    enum_output_path.write_text(enum_result.stdout, encoding="utf-8")
    enum_stderr_path.write_text(enum_result.stderr, encoding="utf-8")

    conclusion = _bootapp_element_conclusion(
        create_supported=create_supported,
        element_probes=element_probes,
        blockers=blockers,
    )
    report = BcdBootappElementProbeReport(
        store_path=store_path,
        bootapp_guid=bootapp_guid,
        create_supported=create_supported,
        element_probes=element_probes,
        enum_output_path=enum_output_path,
        conclusion=conclusion,
        warnings=warnings,
        blockers=blockers,
    )

    payload = {
        "report": report.to_dict(),
        "createstore": {
            "command": list(createstore.command),
            "returncode": createstore.returncode,
            "stdout": createstore.stdout,
            "stderr": createstore.stderr,
        },
        "create_bootapp": {
            "command": list(create_result.command),
            "returncode": create_result.returncode,
            "stdout": create_result.stdout,
            "stderr": create_result.stderr,
        },
        "enum": {
            "command": list(enum_result.command),
            "returncode": enum_result.returncode,
            "stdout_path": str(enum_output_path),
            "stderr_path": str(enum_stderr_path),
        },
        "safety": {
            "uses_offline_store_only": True,
            "system_store_mutation_attempted": False,
            "notes": [
                "All create/set commands include /store <offline-store-path>.",
                "No command targets {bootmgr}, {fwbootmgr}, or system displayorder/default.",
            ],
        },
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    return BcdBootappElementProbeOutcome(
        report=report,
        report_path=report_path,
        enum_stderr_path=enum_stderr_path,
    )


def analyze_bcd_bootapp_probe_report(*, probe_report_path: Path) -> dict[str, object]:
    """Analyze offline BOOTAPP element probe report and suggest next strategy."""
    payload = json.loads(probe_report_path.read_text(encoding="utf-8"))
    report_raw = payload.get("report", {})
    if not isinstance(report_raw, dict):
        raise ValueError("Invalid probe report format: missing report object.")

    create_supported = bool(report_raw.get("create_supported", False))
    conclusion = str(report_raw.get("conclusion", "unknown")).strip().lower()
    element_probes = report_raw.get("element_probes", [])

    device_set_supported = _element_supported(
        element_probes=element_probes,
        element="device",
        value="partition=C:",
    )
    path_set_supported = _element_supported(
        element_probes=element_probes,
        element="path",
        value=_BOOTAPP_PATH_VALUE,
    )

    warnings = [str(item) for item in report_raw.get("warnings", [])]
    blockers = [str(item) for item in report_raw.get("blockers", [])]

    recommended_next_strategy = "blocked"
    confidence: Literal["low", "medium", "high"] = "low"
    if create_supported and device_set_supported and path_set_supported:
        recommended_next_strategy = "firmware-efi-bootapp-system-dry-run"
        confidence = "medium"
        warnings.append(
            "Recommended strategy remains dry-run only; offline parser acceptance "
            "does not prove bootability."
        )
    elif create_supported:
        recommended_next_strategy = "blocked"
        confidence = "low"
        blockers.append(
            "bootapp exists but required elements were not fully accepted in offline probe."
        )
    elif conclusion == "blocked":
        recommended_next_strategy = "blocked"
        confidence = "low"

    return {
        "bootapp_create_supported": create_supported,
        "device_set_supported": device_set_supported,
        "path_set_supported": path_set_supported,
        "recommended_next_strategy": recommended_next_strategy,
        "confidence": confidence,
        "warnings": warnings,
        "blockers": blockers,
    }


def _extract_guid(output: str) -> str | None:
    match = _GUID_RE.search(output)
    if not match:
        return None
    return match.group(0)


def _probe_types_from_help(runner: CommandRunner) -> list[str]:
    result = runner.run(["bcdedit", "/?", "create"], elevated_required=False, check=False)
    text = (result.stdout + "\n" + result.stderr).lower()

    values = list(_BASE_APPLICATION_TYPES)
    discovered: list[str] = []
    for candidate in ("ntldr", "resume", "startup", "memdiag"):
        if candidate in text:
            discovered.append(candidate)

    for item in discovered:
        if item not in values:
            values.append(item)
    return values


def _bootapp_element_conclusion(
    *,
    create_supported: bool,
    element_probes: list[BcdElementSetProbe],
    blockers: list[str],
) -> Literal["bootapp_elements_supported", "bootapp_create_only", "blocked", "unknown"]:
    if not create_supported:
        return "blocked" if blockers else "unknown"

    device_ok = any(
        item.element == "device" and item.value == "partition=C:" and item.supported
        for item in element_probes
    )
    path_ok = any(
        item.element == "path" and item.value == _BOOTAPP_PATH_VALUE and item.supported
        for item in element_probes
    )
    if device_ok and path_ok:
        return "bootapp_elements_supported"
    if element_probes:
        return "bootapp_create_only"
    return "unknown"


def _element_supported(
    *,
    element_probes: object,
    element: str,
    value: str,
) -> bool:
    if not isinstance(element_probes, list):
        return False
    for item in element_probes:
        if not isinstance(item, dict):
            continue
        if str(item.get("element", "")).lower() != element:
            continue
        if str(item.get("value", "")).lower() != value.lower():
            continue
        return bool(item.get("supported", False))
    return False
