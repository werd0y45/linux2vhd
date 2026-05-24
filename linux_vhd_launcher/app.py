"""GUI app entrypoint."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from linux_vhd_launcher.cli import build_installer
from linux_vhd_launcher.gui.main_window import MainWindow
from linux_vhd_launcher.system.windows_privileges import is_windows_platform


def main() -> int:
    """Start the GUI application."""
    app = QApplication(sys.argv)
    installer, _ = build_installer(
        dry_run=not is_windows_platform(),
        execute_real_windows_ops=False,
        confirmation_token=False,
        backup_path=None,
    )
    window = MainWindow(installer)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
