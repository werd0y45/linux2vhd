from __future__ import annotations

import importlib

import pytest


def test_gui_imports() -> None:
    pytest.importorskip("PyQt6")
    importlib.import_module("linux_vhd_launcher.gui.wizard")
    importlib.import_module("linux_vhd_launcher.gui.main_window")
