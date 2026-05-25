"""Data models used across services and interfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from linux_vhd_launcher.errors import ValidationReportFormatError

VALIDATION_REPORT_SCHEMA_VERSION = 2
ValidationStepStatus = Literal["pass", "fail", "skip", "blocked", "not_run"]
ValidationOverallStatus = Literal["pass", "fail", "blocked", "incomplete"]
ProbeStatus = Literal["pass", "fail", "warning", "unknown", "not_applicable"]
CapabilityStatus = Literal["available", "unavailable", "unknown", "blocked"]
RollbackStatus = Literal["not_needed", "pass", "fail", "partial", "not_run"]
TelemetryLevel = Literal["debug", "info", "warning", "error"]
RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(slots=True)
class AppConfig:
    """Application configuration loaded from JSON."""

    default_vhd_dir: Path
    default_vhd_size_gb: int
    bcd_backup_dir: Path
    log_level: str
    catalog_path: Path
    registry_path: Path


@dataclass(slots=True)
class IsoImage:
    """Represents an ISO image file."""

    path: Path
    name: str
    size_bytes: int
    sha256: str | None


@dataclass(slots=True)
class LinuxDistribution:
    """Represents a distribution matched by catalog metadata."""

    name: str
    version: str
    iso: IsoImage
    recommended_size_gb: int
    secure_boot_supported: bool


@dataclass(slots=True)
class VhdSpec:
    """Virtual disk creation parameters."""

    path: Path
    size_gb: int
    format: Literal["vhd", "vhdx"]


@dataclass(slots=True)
class BcdEntry:
    """Boot entry metadata."""

    guid: str
    description: str
    loader_path: str | None


@dataclass(slots=True)
class RegistryItem:
    """Registry record linking a created VHD and BCD entry."""

    distro: str
    vhd_path: Path
    bcd_guid: str
    created_at: datetime
    bcd_backup_path: Path | None


@dataclass(slots=True)
class PlannedStep:
    """A single planned operation step."""

    id: str
    title: str
    command_preview: list[str] | None
    description: str
    dangerous: bool
    rollback: str | None
    docs_url: str | None
    prerequisites: list[str] = field(default_factory=list)
    expected_result: str | None = None
    rollback_action: str | None = None
    verification_action: str | None = None
    risk_level: RiskLevel = "medium"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "command_preview": self.command_preview,
            "description": self.description,
            "dangerous": self.dangerous,
            "rollback": self.rollback,
            "docs_url": self.docs_url,
            "prerequisites": self.prerequisites,
            "expected_result": self.expected_result,
            "rollback_action": self.rollback_action,
            "verification_action": self.verification_action,
            "risk_level": self.risk_level,
        }


@dataclass(slots=True)
class OperationPlan:
    """Top-level structured operation plan."""

    title: str
    target_platform: str
    steps: list[PlannedStep]
    warnings: list[str]
    dangerous: bool
    requires_admin: bool
    experimental: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "target_platform": self.target_platform,
            "steps": [step.to_dict() for step in self.steps],
            "warnings": self.warnings,
            "dangerous": self.dangerous,
            "requires_admin": self.requires_admin,
            "experimental": self.experimental,
        }


@dataclass(slots=True)
class LiveIsoInfo:
    """Metadata discovered from a live Linux ISO payload."""

    iso_path: Path
    distro: str
    version: str | None
    sha256: str
    size_bytes: int
    has_efi_boot: bool
    has_shim: bool
    has_grub: bool
    has_casper_kernel: bool
    kernel_path: str | None
    initrd_path: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "iso_path": str(self.iso_path),
            "distro": self.distro,
            "version": self.version,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "has_efi_boot": self.has_efi_boot,
            "has_shim": self.has_shim,
            "has_grub": self.has_grub,
            "has_casper_kernel": self.has_casper_kernel,
            "kernel_path": self.kernel_path,
            "initrd_path": self.initrd_path,
        }


@dataclass(slots=True)
class LiveVhdLayout:
    """Filesystem layout parameters for live-ISO VHD payload."""

    vhd_path: Path
    format: Literal["vhdx", "vhd"]
    size_gb: int
    efi_partition_size_mb: int
    data_partition_fs: Literal["ntfs", "exfat", "fat32"]
    iso_inside_path: str
    efi_loader_path: str
    grub_cfg_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "vhd_path": str(self.vhd_path),
            "format": self.format,
            "size_gb": self.size_gb,
            "efi_partition_size_mb": self.efi_partition_size_mb,
            "data_partition_fs": self.data_partition_fs,
            "iso_inside_path": self.iso_inside_path,
            "efi_loader_path": self.efi_loader_path,
            "grub_cfg_path": self.grub_cfg_path,
        }


@dataclass(slots=True)
class LiveVhdBuildPlan:
    """Planned live-ISO payload build with explicit warnings and blockers."""

    iso: LiveIsoInfo
    layout: LiveVhdLayout
    steps: list[PlannedStep]
    warnings: list[str]
    blockers: list[str]
    experimental: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "iso": self.iso.to_dict(),
            "layout": self.layout.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "warnings": self.warnings,
            "blockers": self.blockers,
            "experimental": self.experimental,
        }


@dataclass(slots=True)
class StagedEfiFile:
    """Single EFI file planned for staging to ESP."""

    source: str
    destination: str
    sha256: str | None
    required: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "destination": self.destination,
            "sha256": self.sha256,
            "required": self.required,
        }


@dataclass(slots=True)
class EspStagingPlan:
    """Plan for staging EFI files onto Windows ESP."""

    esp_mount_letter: str | None
    staged_dir: str
    files: list[StagedEfiFile]
    requires_esp_write: bool
    secure_boot_warning: str | None
    rollback_steps: list[str]
    blockers: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "esp_mount_letter": self.esp_mount_letter,
            "staged_dir": self.staged_dir,
            "files": [item.to_dict() for item in self.files],
            "requires_esp_write": self.requires_esp_write,
            "secure_boot_warning": self.secure_boot_warning,
            "rollback_steps": self.rollback_steps,
            "blockers": self.blockers,
        }


@dataclass(slots=True)
class BcdApplicationTypeProbe:
    """Single offline BCD application-type probe command result."""

    application_type: str
    supported: bool
    guid: str | None
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    notes: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "application_type": self.application_type,
            "supported": self.supported,
            "guid": self.guid,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "notes": self.notes,
        }


@dataclass(slots=True)
class BcdProbeReport:
    """Offline BCD capability probe report."""

    store_path: Path
    probes: list[BcdApplicationTypeProbe]
    enum_output_path: Path
    supported_types: list[str]
    blocked_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "store_path": str(self.store_path),
            "probes": [item.to_dict() for item in self.probes],
            "enum_output_path": str(self.enum_output_path),
            "supported_types": self.supported_types,
            "blocked_reason": self.blocked_reason,
        }


@dataclass(slots=True)
class BcdElementSetProbe:
    """Single offline BCD element set probe result for bootapp entry."""

    element: str
    value: str
    supported: bool
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    notes: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "element": self.element,
            "value": self.value,
            "supported": self.supported,
            "command": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "notes": self.notes,
        }


@dataclass(slots=True)
class BcdBootappElementProbeReport:
    """Offline BOOTAPP create+element capability probe report."""

    store_path: Path
    bootapp_guid: str | None
    create_supported: bool
    element_probes: list[BcdElementSetProbe]
    enum_output_path: Path
    conclusion: Literal[
        "bootapp_elements_supported",
        "bootapp_create_only",
        "blocked",
        "unknown",
    ]
    warnings: list[str]
    blockers: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "store_path": str(self.store_path),
            "bootapp_guid": self.bootapp_guid,
            "create_supported": self.create_supported,
            "element_probes": [item.to_dict() for item in self.element_probes],
            "enum_output_path": str(self.enum_output_path),
            "conclusion": self.conclusion,
            "warnings": self.warnings,
            "blockers": self.blockers,
        }


@dataclass(slots=True)
class DoctorReport:
    """Structured diagnostics used in validation reports."""

    os: str
    python_version: str
    is_windows: bool
    is_admin: bool
    pyqt6_available: bool
    dry_run_available: bool
    registry_path: str
    config_path: str
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "os": self.os,
            "python_version": self.python_version,
            "is_windows": self.is_windows,
            "is_admin": self.is_admin,
            "pyqt6_available": self.pyqt6_available,
            "dry_run_available": self.dry_run_available,
            "registry_path": self.registry_path,
            "config_path": self.config_path,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DoctorReport:
        try:
            warnings_raw = raw["warnings"]
            if not isinstance(warnings_raw, list):
                raise TypeError("warnings must be list")
            warnings_out = [str(item) for item in warnings_raw]
            return cls(
                os=str(raw["os"]),
                python_version=str(raw["python_version"]),
                is_windows=bool(raw["is_windows"]),
                is_admin=bool(raw["is_admin"]),
                pyqt6_available=bool(raw["pyqt6_available"]),
                dry_run_available=bool(raw["dry_run_available"]),
                registry_path=str(raw["registry_path"]),
                config_path=str(raw["config_path"]),
                warnings=warnings_out,
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Doctor report is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid doctor report: {exc}") from exc


@dataclass(slots=True)
class ProbeResult:
    """Non-destructive capability or environment probe outcome."""

    id: str
    name: str
    status: ProbeStatus
    value: str | bool | int | None
    details: str | None
    source: str | None
    command_preview: list[str] | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "details": self.details,
            "source": self.source,
            "command_preview": self.command_preview,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProbeResult:
        try:
            status = str(raw["status"])
            allowed = {"pass", "fail", "warning", "unknown", "not_applicable"}
            if status not in allowed:
                raise ValueError(f"invalid probe status: {status}")
            value = raw.get("value")
            if value is not None and not isinstance(value, (str, bool, int)):
                raise TypeError("probe value must be str|bool|int|null")
            cmd_raw = raw.get("command_preview")
            if cmd_raw is not None and not isinstance(cmd_raw, list):
                raise TypeError("command_preview must be list or null")
            command_preview = [str(part) for part in cmd_raw] if isinstance(cmd_raw, list) else None
            return cls(
                id=str(raw["id"]),
                name=str(raw["name"]),
                status=cast(ProbeStatus, status),
                value=value,
                details=str(raw["details"]) if raw.get("details") is not None else None,
                source=str(raw["source"]) if raw.get("source") is not None else None,
                command_preview=command_preview,
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Probe result is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid probe result: {exc}") from exc


@dataclass(slots=True)
class CommandEvidence:
    """Normalized command execution evidence for report schema v2."""

    command: list[str]
    exit_code: int | None
    stdout_path: Path | None
    stderr_path: Path | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout_path": str(self.stdout_path) if self.stdout_path else None,
            "stderr_path": str(self.stderr_path) if self.stderr_path else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CommandEvidence:
        try:
            command_raw = raw["command"]
            if not isinstance(command_raw, list):
                raise TypeError("command must be list")
            started_raw = raw.get("started_at")
            finished_raw = raw.get("finished_at")
            return cls(
                command=[str(item) for item in command_raw],
                exit_code=int(raw["exit_code"]) if raw.get("exit_code") is not None else None,
                stdout_path=Path(str(raw["stdout_path"])) if raw.get("stdout_path") else None,
                stderr_path=Path(str(raw["stderr_path"])) if raw.get("stderr_path") else None,
                started_at=datetime.fromisoformat(started_raw)
                if isinstance(started_raw, str)
                else None,
                finished_at=datetime.fromisoformat(finished_raw)
                if isinstance(finished_raw, str)
                else None,
                duration_ms=int(raw["duration_ms"]) if raw.get("duration_ms") is not None else None,
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Command evidence is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid command evidence: {exc}") from exc


@dataclass(slots=True)
class RollbackEvidence:
    """Rollback planning/execution evidence."""

    planned: bool
    attempted: bool
    status: RollbackStatus
    actions: list[str]
    errors: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "planned": self.planned,
            "attempted": self.attempted,
            "status": self.status,
            "actions": self.actions,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RollbackEvidence:
        try:
            status = str(raw["status"])
            allowed = {"not_needed", "pass", "fail", "partial", "not_run"}
            if status not in allowed:
                raise ValueError(f"invalid rollback status: {status}")
            actions_raw = raw.get("actions", [])
            errors_raw = raw.get("errors", [])
            if not isinstance(actions_raw, list) or not isinstance(errors_raw, list):
                raise TypeError("rollback actions/errors must be lists")
            return cls(
                planned=bool(raw["planned"]),
                attempted=bool(raw["attempted"]),
                status=cast(RollbackStatus, status),
                actions=[str(item) for item in actions_raw],
                errors=[str(item) for item in errors_raw],
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Rollback evidence is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid rollback evidence: {exc}") from exc


@dataclass(slots=True)
class BackendCapability:
    """A single backend capability status record."""

    backend: str
    capability: str
    status: CapabilityStatus
    reason: str | None
    docs_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "capability": self.capability,
            "status": self.status,
            "reason": self.reason,
            "docs_url": self.docs_url,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BackendCapability:
        try:
            status = str(raw["status"])
            allowed = {"available", "unavailable", "unknown", "blocked"}
            if status not in allowed:
                raise ValueError(f"invalid capability status: {status}")
            return cls(
                backend=str(raw["backend"]),
                capability=str(raw["capability"]),
                status=cast(CapabilityStatus, status),
                reason=str(raw["reason"]) if raw.get("reason") is not None else None,
                docs_url=str(raw["docs_url"]) if raw.get("docs_url") is not None else None,
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Backend capability is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid backend capability: {exc}") from exc


@dataclass(slots=True)
class CampaignEnvironment:
    """Execution environment metadata captured for campaigns."""

    machine_name: str | None
    os_version: str | None
    is_vm: bool | None
    hypervisor: str | None
    secure_boot: str | None
    bitlocker: str | None
    is_admin: bool
    python_version: str

    def to_dict(self) -> dict[str, object]:
        return {
            "machine_name": self.machine_name,
            "os_version": self.os_version,
            "is_vm": self.is_vm,
            "hypervisor": self.hypervisor,
            "secure_boot": self.secure_boot,
            "bitlocker": self.bitlocker,
            "is_admin": self.is_admin,
            "python_version": self.python_version,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CampaignEnvironment:
        try:
            is_vm_raw = raw.get("is_vm")
            if is_vm_raw is not None and not isinstance(is_vm_raw, bool):
                raise TypeError("is_vm must be bool|null")
            return cls(
                machine_name=str(raw["machine_name"]) if raw.get("machine_name") is not None else None,
                os_version=str(raw["os_version"]) if raw.get("os_version") is not None else None,
                is_vm=is_vm_raw,
                hypervisor=str(raw["hypervisor"]) if raw.get("hypervisor") is not None else None,
                secure_boot=str(raw["secure_boot"]) if raw.get("secure_boot") is not None else None,
                bitlocker=str(raw["bitlocker"]) if raw.get("bitlocker") is not None else None,
                is_admin=bool(raw["is_admin"]),
                python_version=str(raw["python_version"]),
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Campaign environment is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid campaign environment: {exc}") from exc


@dataclass(slots=True)
class TelemetryEvent:
    """Structured telemetry event."""

    timestamp: datetime
    level: TelemetryLevel
    component: str
    event: str
    message: str
    context: dict[str, str | int | bool | None]

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "component": self.component,
            "event": self.event,
            "message": self.message,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TelemetryEvent:
        try:
            level = str(raw["level"])
            if level not in {"debug", "info", "warning", "error"}:
                raise ValueError(f"invalid telemetry level: {level}")
            context_raw = raw.get("context", {})
            if not isinstance(context_raw, dict):
                raise TypeError("context must be an object")
            context: dict[str, str | int | bool | None] = {}
            for key, value in context_raw.items():
                if value is not None and not isinstance(value, (str, int, bool)):
                    raise TypeError("context values must be str|int|bool|null")
                context[str(key)] = value
            return cls(
                timestamp=datetime.fromisoformat(str(raw["timestamp"])),
                level=cast(TelemetryLevel, level),
                component=str(raw["component"]),
                event=str(raw["event"]),
                message=str(raw["message"]),
                context=context,
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Telemetry event is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid telemetry event: {exc}") from exc


@dataclass(slots=True)
class ErrorRecord:
    """Structured error record persisted to validation report."""

    error_type: str
    message: str
    component: str
    recoverable: bool
    suggested_action: str | None
    original_exception: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "error_type": self.error_type,
            "message": self.message,
            "component": self.component,
            "recoverable": self.recoverable,
            "suggested_action": self.suggested_action,
            "original_exception": self.original_exception,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ErrorRecord:
        try:
            return cls(
                error_type=str(raw["error_type"]),
                message=str(raw["message"]),
                component=str(raw["component"]),
                recoverable=bool(raw["recoverable"]),
                suggested_action=str(raw["suggested_action"])
                if raw.get("suggested_action") is not None
                else None,
                original_exception=str(raw["original_exception"])
                if raw.get("original_exception") is not None
                else None,
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Error record is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid error record: {exc}") from exc


@dataclass(slots=True)
class VmRunnerConfig:
    """VM runner orchestration configuration."""

    runner: Literal["manual", "hyperv", "external"]
    vm_name: str | None
    snapshot_name: str | None
    working_dir: Path
    require_snapshot: bool
    allow_mutation: bool


@dataclass(slots=True)
class VmRunnerStatus:
    """Runtime status information for VM runner."""

    runner: Literal["manual", "hyperv", "external"]
    vm_name: str | None
    snapshot_present: bool | None
    can_restore_snapshot: bool | None
    can_export_artifacts: bool | None
    warnings: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "runner": self.runner,
            "vm_name": self.vm_name,
            "snapshot_present": self.snapshot_present,
            "can_restore_snapshot": self.can_restore_snapshot,
            "can_export_artifacts": self.can_export_artifacts,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class ValidationStepResult:
    """Result for a single validation campaign step."""

    id: str
    title: str
    status: ValidationStepStatus
    error: str | None
    docs_url: str | None
    command_evidence: CommandEvidence | None = None
    rollback_evidence: RollbackEvidence | None = None
    probes: list[ProbeResult] = field(default_factory=list)
    capabilities: list[BackendCapability] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "error": self.error,
            "docs_url": self.docs_url,
            "command_evidence": self.command_evidence.to_dict()
            if self.command_evidence
            else None,
            "rollback_evidence": self.rollback_evidence.to_dict()
            if self.rollback_evidence
            else None,
            "probes": [probe.to_dict() for probe in self.probes],
            "capabilities": [cap.to_dict() for cap in self.capabilities],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ValidationStepResult:
        try:
            status = str(raw["status"])
            if status not in {"pass", "fail", "skip", "blocked", "not_run"}:
                raise ValueError(f"invalid status: {status}")
            command_evidence_raw = raw.get("command_evidence")
            rollback_evidence_raw = raw.get("rollback_evidence")
            probes_raw = raw.get("probes", [])
            capabilities_raw = raw.get("capabilities", [])
            if command_evidence_raw is not None and not isinstance(command_evidence_raw, dict):
                raise TypeError("command_evidence must be object or null")
            if rollback_evidence_raw is not None and not isinstance(rollback_evidence_raw, dict):
                raise TypeError("rollback_evidence must be object or null")
            if not isinstance(probes_raw, list) or not isinstance(capabilities_raw, list):
                raise TypeError("probes/capabilities must be lists")
            if any(not isinstance(item, dict) for item in probes_raw):
                raise TypeError("probes must contain objects")
            if any(not isinstance(item, dict) for item in capabilities_raw):
                raise TypeError("capabilities must contain objects")
            return cls(
                id=str(raw["id"]),
                title=str(raw["title"]),
                status=cast(ValidationStepStatus, status),
                error=str(raw["error"]) if raw.get("error") is not None else None,
                docs_url=str(raw["docs_url"]) if raw.get("docs_url") is not None else None,
                command_evidence=CommandEvidence.from_dict(command_evidence_raw)
                if isinstance(command_evidence_raw, dict)
                else None,
                rollback_evidence=RollbackEvidence.from_dict(rollback_evidence_raw)
                if isinstance(rollback_evidence_raw, dict)
                else None,
                probes=[ProbeResult.from_dict(item) for item in probes_raw],
                capabilities=[BackendCapability.from_dict(item) for item in capabilities_raw],
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Validation step is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid validation step: {exc}") from exc


@dataclass(slots=True)
class ValidationArtifact:
    """Artifact metadata produced during validation campaigns."""

    kind: str
    path: Path
    sha256: str | None
    description: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "sha256": self.sha256,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ValidationArtifact:
        try:
            return cls(
                kind=str(raw["kind"]),
                path=Path(str(raw["path"])),
                sha256=str(raw["sha256"]) if raw["sha256"] is not None else None,
                description=str(raw["description"]),
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Validation artifact is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid validation artifact: {exc}") from exc


@dataclass(slots=True)
class ValidationSummary:
    """Roll-up status for campaign execution."""

    passed: int
    failed: int
    skipped: int
    blocked: int
    overall_status: ValidationOverallStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "blocked": self.blocked,
            "overall_status": self.overall_status,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ValidationSummary:
        try:
            overall_status = str(raw["overall_status"])
            if overall_status not in {"pass", "fail", "blocked", "incomplete"}:
                raise ValueError(f"invalid overall_status: {overall_status}")
            overall_status_value = cast(ValidationOverallStatus, overall_status)
            return cls(
                passed=int(raw["passed"]),
                failed=int(raw["failed"]),
                skipped=int(raw["skipped"]),
                blocked=int(raw["blocked"]),
                overall_status=overall_status_value,
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Validation summary is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid validation summary: {exc}") from exc


@dataclass(slots=True)
class ValidationReport:
    """Machine-readable campaign report schema."""

    schema_version: int
    generated_at: datetime
    host: DoctorReport
    campaign_id: str
    vm_snapshot_name: str | None
    steps: list[ValidationStepResult]
    artifacts: list[ValidationArtifact]
    summary: ValidationSummary
    notes: list[str]
    environment: CampaignEnvironment | None = None
    telemetry: list[TelemetryEvent] = field(default_factory=list)
    errors: list[ErrorRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "host": self.host.to_dict(),
            "campaign_id": self.campaign_id,
            "vm_snapshot_name": self.vm_snapshot_name,
            "steps": [step.to_dict() for step in self.steps],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "summary": self.summary.to_dict(),
            "notes": self.notes,
            "environment": self.environment.to_dict() if self.environment else None,
            "telemetry": [event.to_dict() for event in self.telemetry],
            "errors": [error.to_dict() for error in self.errors],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_json(cls, text: str) -> ValidationReport:
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationReportFormatError("Validation report JSON is corrupted.") from exc
        if not isinstance(raw, dict):
            raise ValidationReportFormatError("Validation report root must be an object.")
        return cls.from_dict(raw)

    @classmethod
    def read_json(cls, path: Path) -> ValidationReport:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationReportFormatError(
                f"Could not read validation report: {path}"
            ) from exc
        return cls.from_json(text)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ValidationReport:
        try:
            schema_version = int(raw["schema_version"])
            if schema_version == 1:
                raw = _migrate_report_v1_to_v2(raw)
                schema_version = 2
            elif schema_version != VALIDATION_REPORT_SCHEMA_VERSION:
                raise ValidationReportFormatError(
                    "Unsupported validation report schema_version "
                    f"{schema_version}, expected <= {VALIDATION_REPORT_SCHEMA_VERSION}."
                )

            steps_raw = raw["steps"]
            artifacts_raw = raw["artifacts"]
            notes_raw = raw["notes"]
            if not isinstance(steps_raw, list):
                raise ValidationReportFormatError("Validation report 'steps' must be a list.")
            if not isinstance(artifacts_raw, list):
                raise ValidationReportFormatError("Validation report 'artifacts' must be a list.")
            if not isinstance(notes_raw, list):
                raise ValidationReportFormatError("Validation report 'notes' must be a list.")
            if any(not isinstance(item, dict) for item in steps_raw):
                raise ValidationReportFormatError("Validation report 'steps' must contain objects.")
            if any(not isinstance(item, dict) for item in artifacts_raw):
                raise ValidationReportFormatError(
                    "Validation report 'artifacts' must contain objects."
                )

            host_raw = raw["host"]
            summary_raw = raw["summary"]
            telemetry_raw = raw.get("telemetry", [])
            errors_raw = raw.get("errors", [])
            if not isinstance(host_raw, dict):
                raise ValidationReportFormatError("Validation report 'host' must be an object.")
            if not isinstance(summary_raw, dict):
                raise ValidationReportFormatError("Validation report 'summary' must be an object.")
            if not isinstance(telemetry_raw, list):
                raise ValidationReportFormatError("Validation report 'telemetry' must be a list.")
            if not isinstance(errors_raw, list):
                raise ValidationReportFormatError("Validation report 'errors' must be a list.")
            if any(not isinstance(item, dict) for item in telemetry_raw):
                raise ValidationReportFormatError("Validation report 'telemetry' must contain objects.")
            if any(not isinstance(item, dict) for item in errors_raw):
                raise ValidationReportFormatError("Validation report 'errors' must contain objects.")

            environment_raw = raw.get("environment")
            if environment_raw is not None and not isinstance(environment_raw, dict):
                raise ValidationReportFormatError("Validation report 'environment' must be an object or null.")

            return cls(
                schema_version=schema_version,
                generated_at=datetime.fromisoformat(str(raw["generated_at"])),
                host=DoctorReport.from_dict(host_raw),
                campaign_id=str(raw["campaign_id"]),
                vm_snapshot_name=str(raw["vm_snapshot_name"])
                if raw["vm_snapshot_name"] is not None
                else None,
                steps=[ValidationStepResult.from_dict(item) for item in steps_raw],
                artifacts=[ValidationArtifact.from_dict(item) for item in artifacts_raw],
                summary=ValidationSummary.from_dict(summary_raw),
                notes=[str(item) for item in notes_raw],
                environment=CampaignEnvironment.from_dict(environment_raw)
                if isinstance(environment_raw, dict)
                else None,
                telemetry=[TelemetryEvent.from_dict(item) for item in telemetry_raw],
                errors=[ErrorRecord.from_dict(item) for item in errors_raw],
            )
        except KeyError as exc:
            raise ValidationReportFormatError(
                f"Validation report is missing required field: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise ValidationReportFormatError(f"Invalid validation report: {exc}") from exc


def _migrate_report_v1_to_v2(raw: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(raw)
    migrated["schema_version"] = 2
    migrated["environment"] = None
    migrated["telemetry"] = []
    migrated["errors"] = []

    steps_out: list[dict[str, Any]] = []
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list):
        raise ValidationReportFormatError("Validation report 'steps' must be a list.")

    for step_raw in steps_raw:
        if not isinstance(step_raw, dict):
            raise ValidationReportFormatError("Validation report 'steps' must contain objects.")
        started_raw = step_raw.get("started_at")
        finished_raw = step_raw.get("finished_at")
        duration_ms = None
        if isinstance(started_raw, str) and isinstance(finished_raw, str):
            try:
                started = datetime.fromisoformat(started_raw)
                finished = datetime.fromisoformat(finished_raw)
                duration_ms = int((finished - started).total_seconds() * 1000)
            except ValueError:
                duration_ms = None

        cmd_preview = step_raw.get("command_preview")
        command = [str(part) for part in cmd_preview] if isinstance(cmd_preview, list) else []

        rollback_status_raw = step_raw.get("rollback_status")
        rollback_status: RollbackStatus = "not_run"
        if isinstance(rollback_status_raw, str):
            normalized = rollback_status_raw.strip().lower()
            if normalized in {"not_needed", "pass", "fail", "partial", "not_run"}:
                rollback_status = cast(RollbackStatus, normalized)
            elif "not needed" in normalized:
                rollback_status = "not_needed"

        step_out: dict[str, Any] = {
            "id": str(step_raw.get("id", "unknown")),
            "title": str(step_raw.get("title", "unknown")),
            "status": str(step_raw.get("status", "not_run")),
            "error": str(step_raw["error"]) if step_raw.get("error") is not None else None,
            "docs_url": str(step_raw["docs_url"]) if step_raw.get("docs_url") is not None else None,
            "command_evidence": {
                "command": command,
                "exit_code": 0 if step_raw.get("error") is None else 1,
                "stdout_path": step_raw.get("stdout_path"),
                "stderr_path": step_raw.get("stderr_path"),
                "started_at": started_raw if isinstance(started_raw, str) else None,
                "finished_at": finished_raw if isinstance(finished_raw, str) else None,
                "duration_ms": duration_ms,
            }
            if command
            or step_raw.get("stdout_path")
            or step_raw.get("stderr_path")
            or started_raw
            or finished_raw
            else None,
            "rollback_evidence": {
                "planned": rollback_status != "not_needed",
                "attempted": rollback_status in {"pass", "fail", "partial"},
                "status": rollback_status,
                "actions": [],
                "errors": [str(step_raw["error"])] if step_raw.get("error") else [],
            }
            if rollback_status_raw is not None
            else None,
            "probes": [],
            "capabilities": [],
        }
        steps_out.append(step_out)

    migrated["steps"] = steps_out
    return migrated
