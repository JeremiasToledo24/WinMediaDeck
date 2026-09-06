"""Win32 multi-monitor utilities.

Used by OSD to determine which monitor the cursor is on,
so the overlay appears on the correct display.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)

# MonitorFromPoint flags
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    """Win32 MONITORINFO structure."""
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR

user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int


@dataclass(frozen=True, slots=True)
class MonitorRect:
    """A rectangle describing monitor bounds.

    Attributes:
        left: Left edge x-coordinate.
        top: Top edge y-coordinate.
        width: Width in pixels.
        height: Height in pixels.
    """
    left: int
    top: int
    width: int
    height: int

    @property
    def center_x(self) -> int:
        return self.left + self.width // 2

    @property
    def center_y(self) -> int:
        return self.top + self.height // 2


def get_cursor_position() -> tuple[int, int]:
    """Get the current cursor position.

    Returns:
        (x, y) screen coordinates.
    """
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def get_monitor_at_cursor() -> Optional[MonitorRect]:
    """Get the work area of the monitor containing the cursor.

    Returns:
        MonitorRect for the monitor at the cursor position,
        or None if the query fails.
    """
    cursor_x, cursor_y = get_cursor_position()
    point = wintypes.POINT(cursor_x, cursor_y)

    h_monitor = user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
    if not h_monitor:
        logger.warning("MonitorFromPoint failed")
        return None

    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)

    if not user32.GetMonitorInfoW(h_monitor, ctypes.byref(mi)):
        logger.warning("GetMonitorInfoW failed")
        return None

    rc = mi.rcWork
    return MonitorRect(
        left=rc.left,
        top=rc.top,
        width=rc.right - rc.left,
        height=rc.bottom - rc.top,
    )


def get_display_count() -> int:
    """Return the number of connected monitors."""
    return user32.GetSystemMetrics(80)  # SM_CMONITORS = 80
