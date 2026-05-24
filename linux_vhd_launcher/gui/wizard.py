"""PyQt6 installer wizard UI."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from linux_vhd_launcher.models import VhdSpec
from linux_vhd_launcher.services.installer_service import InstallerService, InstallRequest


class IsoPage(QWizardPage):
    """Wizard page for selecting ISO input."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Step 1: ISO")

        self.iso_edit = QLineEdit()
        self.dir_edit = QLineEdit()
        choose_iso = QPushButton("Browse ISO")
        choose_dir = QPushButton("Browse Directory")
        choose_iso.clicked.connect(self._pick_iso)
        choose_dir.clicked.connect(self._pick_dir)

        layout = QFormLayout()
        layout.addRow("ISO Path", self.iso_edit)
        layout.addRow("", choose_iso)
        layout.addRow("ISO Directory", self.dir_edit)
        layout.addRow("", choose_dir)
        self.setLayout(layout)

    def _pick_iso(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select ISO", "", "ISO (*.iso)")
        if path:
            self.iso_edit.setText(path)

    def _pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select directory")
        if path:
            self.dir_edit.setText(path)


class VhdPage(QWizardPage):
    """Wizard page for VHD/VHDX parameters."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Step 2: VHD")

        self.vhd_path_edit = QLineEdit()
        self.size_box = QSpinBox()
        self.size_box.setRange(8, 2048)
        self.size_box.setValue(40)
        self.format_edit = QLineEdit("vhdx")

        layout = QFormLayout()
        layout.addRow("VHD Path", self.vhd_path_edit)
        layout.addRow("Size (GB)", self.size_box)
        layout.addRow("Format (vhd/vhdx)", self.format_edit)
        self.setLayout(layout)


class SummaryPage(QWizardPage):
    """Wizard page with preflight summary."""

    def __init__(self, wizard: InstallWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Step 3-4: Check and Confirm")
        self.label = QLabel()
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def initializePage(self) -> None:
        self.label.setText(self._wizard.build_summary())


class ProgressPage(QWizardPage):
    """Wizard page running installation and streaming local log text."""

    def __init__(self, wizard: InstallWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("Step 5: Progress")
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.start_button = QPushButton("Start Installation")
        self.start_button.clicked.connect(self._start_install)
        layout = QVBoxLayout()
        layout.addWidget(self.log_view)
        layout.addWidget(self.start_button)
        self.setLayout(layout)

    def _start_install(self) -> None:
        self.log_view.append("Starting install workflow...")
        try:
            result = self._wizard.execute_install()
            self.log_view.append(f"Success. GUID: {result.bcd_guid}")
            if result.warnings:
                for warning in result.warnings:
                    self.log_view.append(f"Warning: {warning}")
        except Exception as exc:
            self.log_view.append(f"Error: {exc}")
            QMessageBox.critical(self, "Install failed", str(exc))


class ResultPage(QWizardPage):
    """Wizard page with final next steps."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Step 6: Result")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Installation finished. Reboot to test Boot Manager entry."))
        self.setLayout(layout)


class InstallWizard(QWizard):
    """High-level installer wizard orchestrating user flow."""

    def __init__(self, installer: InstallerService) -> None:
        super().__init__()
        self.installer = installer
        self.setWindowTitle("Linux VHD Launcher")

        self.iso_page = IsoPage()
        self.vhd_page = VhdPage()
        self.summary_page = SummaryPage(self)
        self.progress_page = ProgressPage(self)
        self.result_page = ResultPage()

        self.addPage(self.iso_page)
        self.addPage(self.vhd_page)
        self.addPage(self.summary_page)
        self.addPage(self.progress_page)
        self.addPage(self.result_page)

    def build_summary(self) -> str:
        """Build summary text from current wizard fields."""
        return (
            f"ISO: {self._iso_path()}\n"
            f"VHD: {self._vhd_path()}\n"
            f"Size: {self.vhd_page.size_box.value()} GB\n"
            f"Format: {self._format()}"
        )

    def execute_install(self):
        """Execute installation via service layer only."""
        spec = VhdSpec(
            path=self._vhd_path(),
            size_gb=self.vhd_page.size_box.value(),
            format=self._format(),
        )
        request = InstallRequest(
            iso_path=self._iso_path(),
            vhd_spec=spec,
            description="Linux VHD Launcher",
            dry_run=False,
        )
        return self.installer.install(request)

    def _iso_path(self) -> Path:
        if self.iso_page.iso_edit.text().strip():
            return Path(self.iso_page.iso_edit.text().strip())
        directory = self.iso_page.dir_edit.text().strip()
        if directory:
            images = self.installer.iso_manager.scan_directory(Path(directory))
            if images:
                return images[0].path
        return Path("")

    def _vhd_path(self) -> Path:
        return Path(self.vhd_page.vhd_path_edit.text().strip())

    def _format(self) -> Literal["vhd", "vhdx"]:
        fmt = self.vhd_page.format_edit.text().strip().lower()
        if fmt not in {"vhd", "vhdx"}:
            return "vhdx"
        return "vhd" if fmt == "vhd" else "vhdx"
