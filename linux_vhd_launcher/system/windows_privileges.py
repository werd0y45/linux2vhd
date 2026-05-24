"""Windows platform and privilege checks."""

from __future__ import annotations

import ctypes
import sys

from linux_vhd_launcher.errors import AdminRequiredError


def is_windows_platform() -> bool:
    """Return True if running on Windows."""
    return sys.platform.startswith("win")


def is_admin() -> bool:
    """Return True if current process has admin rights on Windows."""
    if not is_windows_platform():
        return False
    try:
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def require_windows_admin() -> None:
    """Raise if not running on Windows with admin privileges."""
    if not is_windows_platform():
        raise AdminRequiredError("This operation is available only on Windows.")
    if not is_admin():
        raise AdminRequiredError("Administrator privileges are required for this operation.")
