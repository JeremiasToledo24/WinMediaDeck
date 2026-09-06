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

kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE

kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.OpenEventW.restype = wintypes.HANDLE

kernel32.SetEvent.argtypes = [wintypes.HANDLE]
kernel32.SetEvent.restype = wintypes.BOOL

kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD

# Win32 error codes
ERROR_ALREADY_EXISTS = 183
ERROR_ACCESS_DENIED = 5

MUTEX_NAME = "Local\\WinMediaDeck_Session_Mutex"
QUIT_EVENT_NAME = "Local\\WinMediaDeck_Quit_Event"


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
            "Usa '--quit' para cerrarlo completamente."
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


def create_quit_event() -> Optional[int]:
    """Create the session-scoped named quit event.

    Returns:
        The event handle on success, or None on failure.
    """
    handle = kernel32.CreateEventW(None, False, False, QUIT_EVENT_NAME)
    if not handle:
        logger.warning("Failed to create quit event: error %d", ctypes.get_last_error())
        return None
    logger.debug("Quit event created: handle=%#x", handle)
    return handle


def signal_quit_event() -> bool:
    """Signal the named quit event to request the running instance to stop.

    Returns:
        True if the event was found and signaled, False otherwise.
    """
    EVENT_MODIFY_STATE = 0x0002
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, QUIT_EVENT_NAME)
    if not handle:
        return False
    try:
        success = bool(kernel32.SetEvent(handle))
        logger.debug("Signaled quit event: success=%s", success)
        return success
    finally:
        kernel32.CloseHandle(handle)


def wait_quit_event(handle: int, timeout_ms: int = 500) -> bool:
    """Wait for the quit event to be signaled.

    Args:
        handle: The quit event handle.
        timeout_ms: Timeout in milliseconds.

    Returns:
        True if signaled, False if timeout or error.
    """
    WAIT_OBJECT_0 = 0
    res = kernel32.WaitForSingleObject(handle, timeout_ms)
    return res == WAIT_OBJECT_0


def close_event(handle: Optional[int]) -> None:
    """Close an event handle safely.

    Args:
        handle: The event handle to close.
    """
    if handle:
        kernel32.CloseHandle(handle)
        logger.debug("Event closed: handle=%#x", handle)
