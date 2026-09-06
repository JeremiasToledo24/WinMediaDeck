"""Media controller: executes Action enum members via Win32 SendInput.

Maps each Action to its corresponding virtual key code and dispatches
the key press through the platform abstraction layer.
"""

import logging
from typing import Callable, Optional

from src.models.actions import Action
from src.interfaces.media import IMediaController
from src.platform.windows.input import (
    send_key_press,
    VK_VOLUME_DOWN,
    VK_VOLUME_UP,
    VK_VOLUME_MUTE,
    VK_MEDIA_PREV_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_STOP,
    VK_LAUNCH_APP1,
    VK_LAUNCH_APP2,
    VK_LAUNCH_MEDIA_SELECT,
    VK_LAUNCH_MAIL,
)

logger = logging.getLogger(__name__)

# Mapping from Action enum to virtual key code
_ACTION_VK_MAP: dict[Action, int] = {
    Action.VOLUME_DOWN: VK_VOLUME_DOWN,
    Action.VOLUME_UP: VK_VOLUME_UP,
    Action.MUTE: VK_VOLUME_MUTE,
    Action.PREVIOUS: VK_MEDIA_PREV_TRACK,
    Action.PLAY_PAUSE: VK_MEDIA_PLAY_PAUSE,
    Action.NEXT: VK_MEDIA_NEXT_TRACK,
    Action.STOP: VK_MEDIA_STOP,
    Action.CALCULATOR: VK_LAUNCH_APP1,
    Action.BROWSER: VK_LAUNCH_APP2,
    Action.MEDIA_SELECT: VK_LAUNCH_MEDIA_SELECT,
    Action.MAIL: VK_LAUNCH_MAIL,
}


class MediaController(IMediaController):
    """Concrete media controller using Win32 SendInput.

    TOGGLE_PAUSE is handled specially by the caller (it changes
    app state, not media state), so it does not map to a VK.
    """

    def __init__(
        self,
        on_blocked: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            on_blocked: Optional callback invoked when SendInput is
                        blocked (e.g. by UIPI). Used to update tray state.
        """
        self._on_blocked = on_blocked

    def execute(self, action: Action) -> bool:
        """Execute the given action via SendInput.

        Args:
            action: The Action to execute.

        Returns:
            True if the action was sent successfully.
            False if it was blocked or the action has no VK mapping.
        """
        if action == Action.TOGGLE_PAUSE:
            # TOGGLE_PAUSE is a meta-action handled by the lifecycle,
            # not a media key — return True to signal it was "handled".
            logger.debug("TOGGLE_PAUSE is a meta-action, not a SendInput key")
            return True

        vk = _ACTION_VK_MAP.get(action)
        if vk is None:
            logger.warning("No VK mapping for action %s", action.value)
            return False

        success = send_key_press(vk, extended=True)

        if not success and self._on_blocked:
            self._on_blocked()

        return success
