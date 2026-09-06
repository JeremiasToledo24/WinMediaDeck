"""Win32 low-level keyboard hook via ctypes.

Isolates all SetWindowsHookExW / UnhookWindowsHookEx / CallNextHookEx
calls behind a clean API. The hook callback runs in the thread that
calls start() — that thread MUST pump Windows messages.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Win32 constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
HC_ACTION = 0

# ctypes function signatures
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# LRESULT is a signed pointer-sized integer (LONG_PTR -> wintypes.LPARAM)
LRESULT = wintypes.LPARAM

# HOOKPROC callback type
HOOKPROC: Any = ctypes.CFUNCTYPE(
    LRESULT,              # LRESULT return
    ctypes.c_int,         # nCode
    wintypes.WPARAM,      # wParam (message type)
    wintypes.LPARAM,      # lParam (pointer to KBDLLHOOKSTRUCT)
)

# kernel32 signatures
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

# user32 signatures
user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    wintypes.HINSTANCE,
    wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None

user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.PostThreadMessageW.restype = wintypes.BOOL


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """Windows KBDLLHOOKSTRUCT for low-level keyboard events."""
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


# Transition state flag in KBDLLHOOKSTRUCT.flags
LLKHF_UP = 0x0080
# Injected flag — events we injected ourselves
LLKHF_INJECTED = 0x0010


def install_hook(callback: Any) -> Optional[int]:
    """Install a WH_KEYBOARD_LL hook with the given callback.

    Args:
        callback: A HOOKPROC ctypes callback. Must be kept alive
                  (prevent garbage collection) for the hook's lifetime.

    Returns:
        The hook handle (HHOOK), or None if installation failed.
    """
    h_mod = kernel32.GetModuleHandleW(None)
    hook_handle = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL,
        callback,
        h_mod,
        0,
    )
    if not hook_handle:
        error = ctypes.get_last_error()
        logger.error("SetWindowsHookExW failed with error %d", error)
        return None
    logger.debug("Keyboard hook installed: handle=%#x", hook_handle)
    return hook_handle


def uninstall_hook(hook_handle: int) -> bool:
    """Remove a previously installed keyboard hook.

    Args:
        hook_handle: The HHOOK returned by install_hook().

    Returns:
        True if the hook was successfully removed.
    """
    if not hook_handle:
        return True
    result = user32.UnhookWindowsHookEx(hook_handle)
    if result:
        logger.debug("Keyboard hook removed: handle=%#x", hook_handle)
    else:
        error = ctypes.get_last_error()
        logger.error("UnhookWindowsHookEx failed with error %d", error)
    return bool(result)


def call_next_hook(hook_handle: int, n_code: int, w_param: int, l_param: int) -> int:
    """Pass the hook event to the next handler in the chain.

    Args:
        hook_handle: The HHOOK (can be 0 for LL hooks).
        n_code: The nCode parameter from the callback.
        w_param: The wParam (message type).
        l_param: The lParam (pointer to KBDLLHOOKSTRUCT).

    Returns:
        The value returned by the next hook in the chain.
    """
    return user32.CallNextHookEx(hook_handle, n_code, w_param, l_param)


def pump_messages() -> None:
    """Run the Win32 message pump until WM_QUIT is received.

    This MUST be called on the same thread that installed the hook.
    Blocks until PostQuitMessage() is called.
    """
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    logger.debug("Message pump exited")


def post_quit_message(exit_code: int = 0) -> None:
    """Post WM_QUIT to the current thread's message queue.

    Args:
        exit_code: The exit code to pass (default 0).
    """
    user32.PostQuitMessage(exit_code)


def post_thread_message_quit(thread_id: int) -> bool:
    """Post WM_QUIT to a specific thread's message queue.

    Args:
        thread_id: The target thread's Win32 thread ID.

    Returns:
        True if the message was posted successfully.
    """
    WM_QUIT = 0x0012
    result = user32.PostThreadMessageW(thread_id, WM_QUIT, 0, 0)
    return bool(result)


def get_current_thread_id() -> int:
    """Return the Win32 thread ID of the calling thread."""
    return kernel32.GetCurrentThreadId()
