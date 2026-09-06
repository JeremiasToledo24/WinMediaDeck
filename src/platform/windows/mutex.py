"""Win32 named mutex for single-instance enforcement.

Uses CreateMutexW with a Local\\ session-scoped name to prevent
multiple instances of WinMediaDeck from running simultaneously.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
from typing import Optional

logger = logging.getLogger(__name__)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE

kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
kernel32.ReleaseMutex.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

# Win32 error codes
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5

MUTEX_NAME = "Local\\WinMediaDeck_Session_Mutex"


class MutexError(Exception):
    """Raised when mutex acquisition fails."""
    pass


class AlreadyRunningError(MutexError):
    """Raised when another instance of WinMediaDeck is already running."""
    pass


def acquire_mutex() -> Optional[int]:
    """Attempt to acquire the session-scoped named mutex.

    Returns:
        The mutex handle on success, or None if another instance
        already owns the mutex.

    Raises:
        AlreadyRunningError: If another instance already holds the mutex.
        MutexError: If the mutex could not be created for other reasons.
    """
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)

    if not handle:
        error = ctypes.get_last_error()
        raise MutexError(f"CreateMutexW failed with error {error}")

    error = ctypes.get_last_error()

    if error == ERROR_ALREADY_EXISTS:
        # Another instance is already running
        kernel32.CloseHandle(handle)
        raise AlreadyRunningError(
            "WinMediaDeck ya está en ejecución. "
            "Solo se permite una instancia a la vez."
        )

    logger.debug("Mutex acquired: handle=%#x", handle)
    return handle


def release_mutex(handle: int) -> None:
    """Release and close the mutex handle.

    Args:
        handle: The mutex handle from acquire_mutex().

    Idempotent: safe to call with 0 or None.
    """
    if handle:
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
        logger.debug("Mutex released: handle=%#x", handle)
