"""Main window wrapping the installer wizard."""

from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow

from linux_vhd_launcher.gui.wizard import InstallWizard
from linux_vhd_launcher.services.installer_service import InstallerService


class MainWindow(QMainWindow):
    """Application main window containing the installation wizard."""

    def __init__(self, installer: InstallerService) -> None:
        super().__init__()
        self.setWindowTitle("LinuxVHDLauncher")
        self._wizard = InstallWizard(installer)
        self.setCentralWidget(self._wizard)
