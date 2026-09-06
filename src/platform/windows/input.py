"""Win32 SendInput abstraction for injecting media and system key events.

All keypress simulation is centralised here. SendInput is used instead of
keybd_event for reliability on modern Windows.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import time

logger = logging.getLogger(__name__)

# --- Win32 constants for SendInput ---
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

# --- Virtual Key codes for media/system keys ---
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_LAUNCH_MAIL = 0xB4
VK_LAUNCH_MEDIA_SELECT = 0xB5
VK_LAUNCH_APP1 = 0xB6  # Calculator
VK_LAUNCH_APP2 = 0xB7  # Browser

user32 = ctypes.WinDLL("user32", use_last_error=True)


class MOUSEINPUT(ctypes.Structure):
    """The MOUSEINPUT structure for SendInput."""
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class KEYBDINPUT(ctypes.Structure):
    """The KEYBDINPUT structure for SendInput."""
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class HARDWAREINPUT(ctypes.Structure):
    """The HARDWAREINPUT structure for SendInput."""
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT(ctypes.Structure):
    """The INPUT structure for SendInput."""

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]


user32.SendInput.argtypes = [
    wintypes.UINT,
    ctypes.POINTER(INPUT),
    ctypes.c_int,
]
user32.SendInput.restype = wintypes.UINT

user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT


def _make_key_input(vk: int, flags: int = 0) -> INPUT:
    """Create an INPUT structure for a single key event.

    Args:
        vk: The virtual key code.
        flags: Combination of KEYEVENTF_* flags.

    Returns:
        A populated INPUT structure with hardware scan code.
    """
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = user32.MapVirtualKeyW(vk, 0)
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = 0
    return inp


def send_key_press(vk: int, extended: bool = True) -> bool:
    """Simulate a full key press (down + up) for the given virtual key.

    Uses a realistic 15ms hold time between key down and key up to ensure
    media applications, browsers, and Windows SMTC detect the event.

    Args:
        vk: The virtual key code to simulate.
        extended: Whether to set the KEYEVENTF_EXTENDEDKEY flag (required
                  for media keys).

    Returns:
        True if SendInput reported success for both events.
    """
    flags_down = KEYEVENTF_EXTENDEDKEY if extended else 0
    flags_up = flags_down | KEYEVENTF_KEYUP

    inp_down = (INPUT * 1)(_make_key_input(vk, flags_down))
    inp_up = (INPUT * 1)(_make_key_input(vk, flags_up))

    r_down = user32.SendInput(1, inp_down, ctypes.sizeof(INPUT))
    if r_down != 1:
        error = ctypes.get_last_error()
        logger.warning(
            "SendInput key down failed for VK %#x, result=%d, error=%d",
            vk, r_down, error,
        )
        return False

    time.sleep(0.015)  # 15ms key hold duration

    r_up = user32.SendInput(1, inp_up, ctypes.sizeof(INPUT))
    if r_up != 1:
        error = ctypes.get_last_error()
        logger.warning(
            "SendInput key up failed for VK %#x, result=%d, error=%d",
            vk, r_up, error,
        )
        return False

    logger.debug("SendInput OK for VK %#x", vk)
    return True


def get_last_error() -> int:
    """Return the last Win32 error code."""
    return ctypes.get_last_error()
