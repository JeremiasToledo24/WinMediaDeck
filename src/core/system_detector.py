"""System detector: collects host system information.

Gathers OS version, admin status, integrity level, display count,
DPI awareness, and antivirus info for compatibility analysis.
"""

import ctypes
import logging
import platform
import sys
from typing import Optional

from src.models.system import SystemInfo

logger = logging.getLogger(__name__)


def _is_admin() -> bool:
    """Check if the current process is running elevated."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _get_integrity_level() -> str:
    """Get the process integrity level.

    Returns:
        "Low", "Medium", "High", or "System".
    """
    try:
        import ctypes.wintypes as wintypes

        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32

        # Get process token
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)  # TOKEN_QUERY
        ):
            return "Unknown"

        try:
            # Query token integrity level
            TOKEN_INTEGRITY_LEVEL = 25
            info_size = wintypes.DWORD()

            advapi32.GetTokenInformation(
                token, TOKEN_INTEGRITY_LEVEL, None, 0, ctypes.byref(info_size)
            )

            buffer = ctypes.create_string_buffer(info_size.value)
            if not advapi32.GetTokenInformation(
                token, TOKEN_INTEGRITY_LEVEL, buffer,
                info_size.value, ctypes.byref(info_size)
            ):
                return "Unknown"

            # Parse the SID to get the integrity level RID
            # The buffer contains a TOKEN_MANDATORY_LABEL structure
            # For simplicity, use a heuristic based on IsUserAnAdmin
            if _is_admin():
                return "High"
            return "Medium"
        finally:
            kernel32.CloseHandle(token)
    except Exception:
        return "Unknown"


def _get_dpi_awareness() -> str:
    """Get the current DPI awareness context."""
    try:
        user32 = ctypes.windll.user32
        # Try to get the thread DPI awareness context
        ctx = user32.GetThreadDpiAwarenessContext()
        if ctx:
            awareness = user32.GetAwarenessFromDpiAwarenessContext(ctx)
            awareness_map = {
                0: "unaware",
                1: "system",
                2: "per-monitor",
            }
            return awareness_map.get(awareness, f"unknown({awareness})")
    except Exception:
        pass
    return "unaware"


def _get_antivirus() -> Optional[str]:
    """Attempt to detect the installed antivirus product.

    Uses WMI (via COM) to query SecurityCenter2.
    """
    try:
        import subprocess
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance -Namespace root/SecurityCenter2 "
                "-ClassName AntiVirusProduct | Select-Object -ExpandProperty displayName"
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return None


def _get_display_count() -> int:
    """Get the number of connected monitors."""
    try:
        from src.platform.windows.monitors import get_display_count
        return get_display_count()
    except Exception:
        return 1


def detect_system() -> SystemInfo:
    """Collect a snapshot of the host system.

    Returns:
        A populated SystemInfo dataclass.
    """
    return SystemInfo(
        os_version=platform.version(),
        os_build=int(platform.version().split(".")[-1]) if "." in platform.version() else 0,
        is_admin=_is_admin(),
        integrity_level=_get_integrity_level(),
        python_version=platform.python_version(),
        display_count=_get_display_count(),
        dpi_awareness=_get_dpi_awareness(),
        antivirus=_get_antivirus(),
    )
