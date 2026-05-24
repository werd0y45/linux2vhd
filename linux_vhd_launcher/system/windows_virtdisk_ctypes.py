"""ctypes constants and signatures for Win32 virtdisk API."""

from __future__ import annotations

import ctypes
import os
import sys
import uuid
from ctypes import POINTER, Structure, Union, byref, c_int64, c_uint32, c_void_p
from ctypes.wintypes import DWORD, HANDLE, LPCWSTR
from pathlib import Path
from typing import Any

from linux_vhd_launcher.errors import VhdOperationError

# Basic constants used in v0.3 skeleton.
VIRTUAL_STORAGE_TYPE_DEVICE_UNKNOWN = 0
VIRTUAL_STORAGE_TYPE_DEVICE_ISO = 1
VIRTUAL_STORAGE_TYPE_DEVICE_VHD = 2
VIRTUAL_STORAGE_TYPE_DEVICE_VHDX = 3

CREATE_VIRTUAL_DISK_PARAMETERS_VERSION_1 = 1
CREATE_VIRTUAL_DISK_PARAMETERS_VERSION_2 = 2
OPEN_VIRTUAL_DISK_VERSION_1 = 1

CREATE_VIRTUAL_DISK_FLAG_NONE = 0
OPEN_VIRTUAL_DISK_FLAG_NONE = 0
ATTACH_VIRTUAL_DISK_FLAG_NONE = 0
DETACH_VIRTUAL_DISK_FLAG_NONE = 0

VIRTUAL_DISK_ACCESS_NONE = 0
VIRTUAL_DISK_ACCESS_ATTACH_RO = 0x00010000
VIRTUAL_DISK_ACCESS_ATTACH_RW = 0x00020000
VIRTUAL_DISK_ACCESS_DETACH = 0x00040000
VIRTUAL_DISK_ACCESS_GET_INFO = 0x00080000
VIRTUAL_DISK_ACCESS_CREATE = 0x00100000
VIRTUAL_DISK_ACCESS_METAOPS = 0x00200000
VIRTUAL_DISK_ACCESS_READ = 0x000D0000
VIRTUAL_DISK_ACCESS_ALL = 0x003F0000

ERROR_SUCCESS = 0


class GUID(Structure):
    _fields_ = [
        ("Data1", c_uint32),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid_from_uuid(value: uuid.UUID) -> GUID:
    b = value.bytes_le
    return GUID(
        Data1=int.from_bytes(b[0:4], "little"),
        Data2=int.from_bytes(b[4:6], "little"),
        Data3=int.from_bytes(b[6:8], "little"),
        Data4=(ctypes.c_ubyte * 8).from_buffer_copy(b[8:16]),
    )


VIRTUAL_STORAGE_TYPE_VENDOR_MICROSOFT = _guid_from_uuid(
    uuid.UUID("ec984aec-a0f9-47e9-901f-71415a66345b")
)


class VIRTUAL_STORAGE_TYPE(Structure):
    _fields_ = [
        ("DeviceId", DWORD),
        ("VendorId", GUID),
    ]


class CREATE_VIRTUAL_DISK_PARAMETERS_V2(Structure):
    _fields_ = [
        ("UniqueId", GUID),
        ("MaximumSize", c_int64),
        ("BlockSizeInBytes", DWORD),
        ("SectorSizeInBytes", DWORD),
        ("PhysicalSectorSizeInBytes", DWORD),
        ("ParentPath", LPCWSTR),
        ("SourcePath", LPCWSTR),
        ("OpenFlags", DWORD),
        ("ParentVirtualStorageType", VIRTUAL_STORAGE_TYPE),
        ("SourceVirtualStorageType", VIRTUAL_STORAGE_TYPE),
        ("ResiliencyGuid", GUID),
    ]


class CREATE_VIRTUAL_DISK_PARAMETERS_UNION(Union):
    _fields_ = [
        ("Version2", CREATE_VIRTUAL_DISK_PARAMETERS_V2),
    ]


class CREATE_VIRTUAL_DISK_PARAMETERS(Structure):
    _anonymous_ = ("_union",)
    _fields_ = [
        ("Version", DWORD),
        ("_union", CREATE_VIRTUAL_DISK_PARAMETERS_UNION),
    ]


class OPEN_VIRTUAL_DISK_PARAMETERS_V1(Structure):
    _fields_ = [("RWDepth", DWORD)]


class OPEN_VIRTUAL_DISK_PARAMETERS_UNION(Union):
    _fields_ = [("Version1", OPEN_VIRTUAL_DISK_PARAMETERS_V1)]


class OPEN_VIRTUAL_DISK_PARAMETERS(Structure):
    _anonymous_ = ("_union",)
    _fields_ = [
        ("Version", DWORD),
        ("_union", OPEN_VIRTUAL_DISK_PARAMETERS_UNION),
    ]


class WinVirtDiskApi:
    """Wrapper around virtdisk.dll exports.

    Real WinAPI calls are disabled by default and require
    LINUX_VHD_LAUNCHER_ENABLE_VIRTDISK_CTYPES=1.
    """

    def __init__(self, *, enabled: bool | None = None) -> None:
        self._enabled = (
            enabled
            if enabled is not None
            else os.getenv("LINUX_VHD_LAUNCHER_ENABLE_VIRTDISK_CTYPES") == "1"
        )
        self._dll: Any = None
        self._create_virtual_disk: Any = None
        self._open_virtual_disk: Any = None
        self._attach_virtual_disk: Any = None
        self._detach_virtual_disk: Any = None
        self._close_handle: Any = None
        if self._enabled and sys.platform.startswith("win"):
            self._dll = ctypes.WinDLL(  # pyright: ignore[reportAttributeAccessIssue]
                "virtdisk",
                use_last_error=True,
            )
            self._bind()

    def _bind(self) -> None:
        assert self._dll is not None
        self._create_virtual_disk = self._dll.CreateVirtualDisk
        self._create_virtual_disk.argtypes = [
            POINTER(VIRTUAL_STORAGE_TYPE),
            LPCWSTR,
            DWORD,
            c_void_p,
            DWORD,
            DWORD,
            POINTER(CREATE_VIRTUAL_DISK_PARAMETERS),
            c_void_p,
            POINTER(HANDLE),
        ]
        self._create_virtual_disk.restype = DWORD

        self._open_virtual_disk = self._dll.OpenVirtualDisk
        self._open_virtual_disk.argtypes = [
            POINTER(VIRTUAL_STORAGE_TYPE),
            LPCWSTR,
            DWORD,
            DWORD,
            POINTER(OPEN_VIRTUAL_DISK_PARAMETERS),
            POINTER(HANDLE),
        ]
        self._open_virtual_disk.restype = DWORD

        self._attach_virtual_disk = self._dll.AttachVirtualDisk
        self._attach_virtual_disk.argtypes = [
            HANDLE,
            c_void_p,
            DWORD,
            DWORD,
            c_void_p,
            c_void_p,
        ]
        self._attach_virtual_disk.restype = DWORD

        self._detach_virtual_disk = self._dll.DetachVirtualDisk
        self._detach_virtual_disk.argtypes = [HANDLE, DWORD, DWORD]
        self._detach_virtual_disk.restype = DWORD

        self._close_handle = ctypes.windll.kernel32.CloseHandle  # type: ignore[attr-defined]
        self._close_handle.argtypes = [HANDLE]
        self._close_handle.restype = ctypes.c_int

    def create_virtual_disk(
        self,
        *,
        storage_type: VIRTUAL_STORAGE_TYPE,
        path: Path,
        access_mask: int,
        create_flags: int,
        parameters: CREATE_VIRTUAL_DISK_PARAMETERS,
    ) -> int:
        self._ensure_enabled("CreateVirtualDisk")
        assert self._dll is not None

        handle = HANDLE()
        result = self._create_virtual_disk(
            byref(storage_type),
            str(path),
            access_mask,
            None,
            create_flags,
            0,
            byref(parameters),
            None,
            byref(handle),
        )
        self._check_result(result, "CreateVirtualDisk")
        if handle.value is None:
            raise VhdOperationError("CreateVirtualDisk returned null handle")
        return int(handle.value)

    def open_virtual_disk(
        self,
        *,
        storage_type: VIRTUAL_STORAGE_TYPE,
        path: Path,
        access_mask: int,
        open_flags: int,
        parameters: OPEN_VIRTUAL_DISK_PARAMETERS,
    ) -> int:
        self._ensure_enabled("OpenVirtualDisk")
        assert self._dll is not None

        handle = HANDLE()
        result = self._open_virtual_disk(
            byref(storage_type),
            str(path),
            access_mask,
            open_flags,
            byref(parameters),
            byref(handle),
        )
        self._check_result(result, "OpenVirtualDisk")
        if handle.value is None:
            raise VhdOperationError("OpenVirtualDisk returned null handle")
        return int(handle.value)

    def attach_virtual_disk(self, *, handle: int, flags: int) -> None:
        self._ensure_enabled("AttachVirtualDisk")
        result = self._attach_virtual_disk(HANDLE(handle), None, flags, 0, None, None)
        self._check_result(result, "AttachVirtualDisk")

    def detach_virtual_disk(self, *, handle: int, flags: int) -> None:
        self._ensure_enabled("DetachVirtualDisk")
        result = self._detach_virtual_disk(HANDLE(handle), flags, 0)
        self._check_result(result, "DetachVirtualDisk")

    def close_handle(self, handle: int) -> None:
        if not self._enabled:
            return
        if handle == 0:
            return
        ok = self._close_handle(HANDLE(handle))
        if ok == 0:
            get_last_error = getattr(ctypes, "get_last_error", lambda: 0)
            last_error = int(get_last_error())
            message = _format_win_error(last_error)
            raise VhdOperationError(
                f"CloseHandle failed for handle {handle}: {last_error} ({message})"
            )

    def _ensure_enabled(self, function_name: str) -> None:
        if not self._enabled:
            raise VhdOperationError(
                f"{function_name} is behind feature flag. "
                "Set LINUX_VHD_LAUNCHER_ENABLE_VIRTDISK_CTYPES=1 for Windows VM experiments."
            )
        if not sys.platform.startswith("win"):
            raise VhdOperationError(f"{function_name} is available only on Windows.")

    def _check_result(self, error_code: int, function_name: str) -> None:
        if error_code != ERROR_SUCCESS:
            message = _format_win_error(error_code)
            raise VhdOperationError(
                f"{function_name} failed with error code {error_code}: {message}"
            )


def _format_win_error(error_code: int) -> str:
    formatter = getattr(ctypes, "FormatError", None)
    if formatter is None:
        return "unknown error"
    try:
        return str(formatter(error_code)).strip()
    except Exception:
        return "unknown error"
