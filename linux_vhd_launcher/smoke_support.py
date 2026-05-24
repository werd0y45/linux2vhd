"""Helpers shared by smoke scripts and tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SmokeRequirementStatus:
    """Structured smoke preflight result."""

    ok: bool
    errors: list[str]


def evaluate_offline_requirements(
    *,
    venv_exists: bool,
    pyqt6_available: bool,
    ruff_available: bool,
    mypy_available: bool,
) -> SmokeRequirementStatus:
    """Validate prerequisites for offline smoke mode."""
    errors: list[str] = []
    if not venv_exists:
        errors.append("venv missing")
    if not pyqt6_available:
        errors.append("PyQt6 missing")
    if not ruff_available:
        errors.append("ruff missing")
    if not mypy_available:
        errors.append("mypy missing")
    return SmokeRequirementStatus(ok=not errors, errors=errors)


def render_smoke_error(reason: str) -> str:
    """Map internal failure reason to actionable smoke script message."""
    mapping = {
        "network": "network unavailable",
        "venv": "venv missing",
        "ruff": "ruff missing",
        "mypy": "mypy missing",
        "pyqt6": "PyQt6 missing",
    }
    return mapping.get(reason, reason)
