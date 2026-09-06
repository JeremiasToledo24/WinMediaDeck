"""Unit tests for the mutex module."""

import pytest
from unittest.mock import patch, MagicMock

from src.platform.windows.mutex import (
    acquire_mutex,
    release_mutex,
    AlreadyRunningError,
    MutexError,
    MUTEX_NAME,
    ERROR_ALREADY_EXISTS,
)


class TestMutex:
    """Tests for mutex acquisition and release."""

    @patch("src.platform.windows.mutex.kernel32")
    def test_acquire_success(self, mock_kernel32):
        """Mutex is acquired successfully."""
        mock_kernel32.CreateMutexW.return_value = 12345
        mock_kernel32.GetLastError = MagicMock(return_value=0)

        # Patch ctypes.get_last_error to return 0
        with patch("src.platform.windows.mutex.ctypes") as mock_ctypes:
            mock_ctypes.windll.kernel32 = mock_kernel32
            mock_ctypes.get_last_error.return_value = 0

            # Re-import to use mocked ctypes
            from src.platform.windows import mutex
            mock_original_kernel = mutex.kernel32
            mutex.kernel32 = mock_kernel32

            try:
                handle = mutex.acquire_mutex()
                assert handle == 12345
                mock_kernel32.CreateMutexW.assert_called_once_with(
                    None, True, MUTEX_NAME
                )
            finally:
                mutex.kernel32 = mock_original_kernel

    @patch("src.platform.windows.mutex.kernel32")
    @patch("src.platform.windows.mutex.ctypes")
    def test_acquire_already_running(self, mock_ctypes, mock_kernel32):
        """Second instance raises AlreadyRunningError."""
        mock_kernel32.CreateMutexW.return_value = 12345
        mock_ctypes.get_last_error.return_value = ERROR_ALREADY_EXISTS

        from src.platform.windows import mutex
        original = mutex.kernel32
        mutex.kernel32 = mock_kernel32

        try:
            with pytest.raises(AlreadyRunningError, match="ya está en ejecución"):
                mutex.acquire_mutex()
            # Verify handle was closed
            mock_kernel32.CloseHandle.assert_called_once_with(12345)
        finally:
            mutex.kernel32 = original

    @patch("src.platform.windows.mutex.kernel32")
    @patch("src.platform.windows.mutex.ctypes")
    def test_acquire_creation_failure(self, mock_ctypes, mock_kernel32):
        """CreateMutexW returning 0 raises MutexError."""
        mock_kernel32.CreateMutexW.return_value = 0
        mock_ctypes.get_last_error.return_value = 5  # ACCESS_DENIED

        from src.platform.windows import mutex
        original = mutex.kernel32
        mutex.kernel32 = mock_kernel32

        try:
            with pytest.raises(MutexError, match="failed with error"):
                mutex.acquire_mutex()
        finally:
            mutex.kernel32 = original

    def test_release_none_handle(self):
        """release_mutex with None handle is safe (idempotent)."""
        # Should not raise
        release_mutex(None)
        release_mutex(0)

    def test_mutex_name_format(self):
        """Mutex name follows the Local\\ session-scoped convention."""
        assert MUTEX_NAME.startswith("Local\\")
        assert "WinMediaDeck" in MUTEX_NAME
