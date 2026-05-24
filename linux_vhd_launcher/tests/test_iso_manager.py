from __future__ import annotations

from pathlib import Path

import pytest

from linux_vhd_launcher.errors import IsoValidationError
from linux_vhd_launcher.services.iso_manager import ISOManager


def test_iso_manager_scans_directory(tmp_path: Path) -> None:
    (tmp_path / "a.iso").write_bytes(b"iso-a")
    (tmp_path / "b.iso").write_bytes(b"iso-b")
    (tmp_path / "not_iso.txt").write_text("x", encoding="utf-8")

    manager = ISOManager(tmp_path / "catalog.json")
    images = manager.scan_directory(tmp_path)

    assert [image.name for image in images] == ["a.iso", "b.iso"]


def test_iso_manager_sha256(tmp_path: Path) -> None:
    payload = b"abc123"
    iso_path = tmp_path / "x.iso"
    iso_path.write_bytes(payload)

    manager = ISOManager(tmp_path / "catalog.json")
    digest = manager.calculate_sha256(iso_path)

    assert digest == "6ca13d52ca70c883e0f0bb101e425a89e8624de51db2d2392593af6a84118090"


def test_iso_manager_validate_missing(tmp_path: Path) -> None:
    manager = ISOManager(tmp_path / "catalog.json")
    with pytest.raises(IsoValidationError):
        manager.validate_iso(tmp_path / "missing.iso")


def test_iso_manager_validate_extension(tmp_path: Path) -> None:
    manager = ISOManager(tmp_path / "catalog.json")
    text_file = tmp_path / "a.txt"
    text_file.write_text("x", encoding="utf-8")

    with pytest.raises(IsoValidationError):
        manager.validate_iso(text_file)
