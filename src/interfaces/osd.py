"""Contract for the On-Screen Display (OSD) service."""

from abc import ABC, abstractmethod

from src.models.actions import Action


class IOSDService(ABC):
    """Abstract interface for the HUD overlay display.

    Implementations should be non-blocking: show() queues the
    display request and returns immediately. The OSD renders
    on the monitor where the cursor is currently positioned.
    """

    @abstractmethod
    def show(self, action: Action) -> None:
        """Display an OSD notification for the given action.

        Args:
            action: The action that was just executed.
        """
        ...

    @abstractmethod
    def hide(self) -> None:
        """Immediately hide any visible OSD notification."""
        ...

    @abstractmethod
    def shutdown(self) -> None:
        """Cleanly shut down the OSD subsystem.

        Must be idempotent — safe to call multiple times.
        """
        ...
