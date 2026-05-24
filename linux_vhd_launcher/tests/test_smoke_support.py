from __future__ import annotations

from linux_vhd_launcher.smoke_support import evaluate_offline_requirements, render_smoke_error


def test_offline_requirements_collect_missing_components() -> None:
    status = evaluate_offline_requirements(
        venv_exists=False,
        pyqt6_available=False,
        ruff_available=False,
        mypy_available=True,
    )
    assert status.ok is False
    assert "venv missing" in status.errors
    assert "PyQt6 missing" in status.errors
    assert "ruff missing" in status.errors


def test_render_smoke_error_mapping() -> None:
    assert render_smoke_error("network") == "network unavailable"
    assert render_smoke_error("mypy") == "mypy missing"
