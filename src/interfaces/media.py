"""Contract for the media action controller."""

from abc import ABC, abstractmethod

from src.models.actions import Action


class IMediaController(ABC):
    """Abstract interface for executing media/system actions.

    Implementations translate Action enum members into platform-specific
    API calls (e.g. Win32 SendInput with VK_MEDIA_* keys).
    """

    @abstractmethod
    def execute(self, action: Action) -> bool:
        """Execute the given action.

        Args:
            action: The Action enum member to execute.

        Returns:
            True if the action was executed successfully,
            False if it was blocked (e.g. by UIPI).
        """
        ...
