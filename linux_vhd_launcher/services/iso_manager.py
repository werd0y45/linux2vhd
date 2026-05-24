"""ISO discovery, hashing, and catalog matching."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from linux_vhd_launcher.errors import IsoValidationError
from linux_vhd_launcher.models import IsoImage, LinuxDistribution


@dataclass(slots=True)
class ISOManager:
    """Service for ISO file scanning and validation."""

    catalog_path: Path

    def scan_directory(self, directory: Path) -> list[IsoImage]:
        """Return discovered .iso files in a directory."""
        if not directory.exists() or not directory.is_dir():
            raise IsoValidationError(f"ISO directory does not exist: {directory}")
        images: list[IsoImage] = []
        for path in sorted(directory.glob("*.iso")):
            images.append(
                IsoImage(
                    path=path,
                    name=path.name,
                    size_bytes=path.stat().st_size,
                    sha256=None,
                )
            )
        return images

    def build_iso(self, iso_path: Path, *, with_sha256: bool = True) -> IsoImage:
        """Build an IsoImage object for a single path."""
        self.validate_iso(iso_path)
        sha256 = self.calculate_sha256(iso_path) if with_sha256 else None
        return IsoImage(
            path=iso_path,
            name=iso_path.name,
            size_bytes=iso_path.stat().st_size,
            sha256=sha256,
        )

    def validate_iso(self, iso_path: Path) -> None:
        """Validate that a given path points to a readable ISO file."""
        if not iso_path.exists() or not iso_path.is_file():
            raise IsoValidationError(f"ISO file not found: {iso_path}")
        if iso_path.suffix.lower() != ".iso":
            raise IsoValidationError("Selected file is not an .iso image.")
        if iso_path.stat().st_size <= 0:
            raise IsoValidationError("ISO file is empty.")

    def calculate_sha256(self, path: Path) -> str:
        """Calculate SHA-256 for a file."""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def match_catalog(self, iso: IsoImage) -> LinuxDistribution | None:
        """Match an ISO image against catalog metadata."""
        if not self.catalog_path.exists():
            return None

        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        rows = raw.get("distributions", raw)
        if not isinstance(rows, list):
            return None

        for row_any in rows:
            if not isinstance(row_any, dict):
                continue
            row: dict[str, Any] = row_any
            if self._is_match(row, iso):
                return LinuxDistribution(
                    name=str(row.get("name", "Unknown Linux")),
                    version=str(row.get("version", "unknown")),
                    iso=iso,
                    recommended_size_gb=int(row.get("recommended_size_gb", 40)),
                    secure_boot_supported=bool(row.get("secure_boot_supported", False)),
                )
        return None

    def _is_match(self, row: dict[str, Any], iso: IsoImage) -> bool:
        sha = row.get("sha256")
        filename_contains = str(row.get("filename_contains", "")).lower().strip()
        if sha and iso.sha256 and str(sha).lower() == iso.sha256.lower():
            return True
        if filename_contains and filename_contains in iso.name.lower():
            return True
        return False
