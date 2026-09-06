"""Contract for the keyboard hook subsystem."""

from abc import ABC, abstractmethod
from typing import Callable, Optional

from src.models.events import HotkeyEvent


class IKeyboardHook(ABC):
    """Abstract interface for a global keyboard hook.

    Implementations must guarantee:
    - The hook callback runs in < 1 ms (no blocking).
    - Events are queued, not processed inline.
    - Cleanup via stop() removes the hook from Windows.
    """

    @abstractmethod
    def start(self, callback: Callable[[HotkeyEvent], None]) -> None:
        """Install the low-level keyboard hook and start the message pump.

        Args:
            callback: Invoked for each relevant HotkeyEvent. Must not block.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Remove the keyboard hook and stop the message pump.

        Must be idempotent — safe to call multiple times.
        """
        ...

    @abstractmethod
    def is_installed(self) -> bool:
        """Return True if the hook is currently active in Windows."""
        ...

    @abstractmethod
    def reinstall(self) -> bool:
        """Re-install the hook if it was silently removed by Windows.

        Returns:
            True if the hook was successfully reinstalled.
        """
        ...
