"""GRUB configuration generation for Ubuntu live ISO loopback boot."""

from __future__ import annotations

from dataclasses import dataclass

from linux_vhd_launcher.errors import LinuxVhdLauncherError


class GrubConfigError(LinuxVhdLauncherError):
    """Raised when grub.cfg generation inputs are invalid."""


@dataclass(slots=True)
class GrubLiveIsoConfig:
    """Inputs required to generate a loopback ISO GRUB menu entry."""

    iso_inside_path: str
    kernel_path: str
    initrd_path: str
    menu_title: str = "Ubuntu Live ISO"
    boot_params: str = "boot=casper iso-scan/filename={iso_path} quiet splash ---"


def generate_ubuntu_loopback_grub_cfg(config: GrubLiveIsoConfig) -> str:
    """Generate a minimal GRUB config for Ubuntu live ISO boot."""
    iso_path = _normalized_abs_path(config.iso_inside_path)
    kernel_path = _normalized_abs_path(config.kernel_path)
    initrd_path = _normalized_abs_path(config.initrd_path)

    params = config.boot_params.format(iso_path=iso_path)

    return "\n".join(
        [
            "set default=0",
            "set timeout=5",
            "",
            f"menuentry \"{config.menu_title}\" {{",
            f"    search --no-floppy --set=iso_root --file {iso_path}",
            "    set root=($iso_root)",
            f"    loopback loop {iso_path}",
            f"    linux (loop){kernel_path} {params}",
            f"    initrd (loop){initrd_path}",
            "    boot",
            "}",
            "",
        ]
    )


def _normalized_abs_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    if not value.startswith("/"):
        raise GrubConfigError(f"Path must be absolute inside filesystem image: {raw}")
    if " " in value:
        raise GrubConfigError(f"Path must not contain spaces for this demo template: {raw}")
    return value
