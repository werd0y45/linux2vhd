"""Domain exceptions for LinuxVHDLauncher."""


class LinuxVhdLauncherError(Exception):
    """Base error for the application domain."""


class AdminRequiredError(LinuxVhdLauncherError):
    """Raised when an admin-only operation is requested without privileges."""


class InsufficientSpaceError(LinuxVhdLauncherError):
    """Raised when disk space is insufficient for a VHD operation."""


class IsoValidationError(LinuxVhdLauncherError):
    """Raised when ISO validation fails."""


class VhdOperationError(LinuxVhdLauncherError):
    """Raised when a VHD operation fails."""


class BcdOperationError(LinuxVhdLauncherError):
    """Raised when a BCD operation fails."""


class SecureBootChainError(LinuxVhdLauncherError):
    """Raised when secure-boot-required files are missing."""


class RollbackError(LinuxVhdLauncherError):
    """Raised when rollback cannot be completed safely."""


class UnsupportedPlatformError(LinuxVhdLauncherError):
    """Raised when an operation is requested on an unsupported platform."""


class UnsupportedBootChainError(LinuxVhdLauncherError):
    """Raised when requested boot-chain mode is not supported."""


class RegistryError(LinuxVhdLauncherError):
    """Raised when local registry file handling fails."""


class DuplicateRegistryGuidError(RegistryError):
    """Raised when the same BCD GUID is added to registry twice."""


class RegistryFormatError(RegistryError):
    """Raised when registry JSON is corrupted or has an invalid schema."""


class ExperimentalBootChainWarning(UserWarning):
    """Warning used for boot chains that require validation on real Windows hosts."""


class UnsafeRealOperationError(LinuxVhdLauncherError):
    """Raised when real Windows operations are requested without explicit safety gate."""


class ValidationReportFormatError(LinuxVhdLauncherError):
    """Raised when validation report JSON is corrupted or schema-incompatible."""
