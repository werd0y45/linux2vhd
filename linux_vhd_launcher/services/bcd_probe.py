"""Offline BCD application-type capability probe helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from linux_vhd_launcher.errors import UnsupportedPlatformError
from linux_vhd_launcher.models import BcdApplicationTypeProbe, BcdProbeReport
from linux_vhd_launcher.system.runner import CommandRunner
from linux_vhd_launcher.system.windows_privileges import is_windows_platform

_GUID_RE = re.compile(r"\{[0-9a-fA-F\-]+\}")
_BASE_APPLICATION_TYPES = ("osloader", "bootsector", "bootapp")


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
