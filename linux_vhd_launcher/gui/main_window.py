"""Main window wrapping the installer wizard."""

from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow, QTabWidget

from linux_vhd_launcher.gui.wizard import InstallWizard, LiveDemoPage
from linux_vhd_launcher.services.installer_service import InstallerService


class MainWindow(QMainWindow):
    """Application main window containing the installation wizard."""

    def __init__(self, installer: InstallerService) -> None:
        super().__init__()
        self.setWindowTitle("LinuxVHDLauncher")
        self._wizard = InstallWizard(installer)
        self._live_demo_tab = LiveDemoPage()
        tabs = QTabWidget()
        tabs.addTab(self._wizard, "Installer Wizard")
        tabs.addTab(self._live_demo_tab, "Live VHD Demo")
        self.setCentralWidget(tabs)
