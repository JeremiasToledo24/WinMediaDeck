"""Action router: maps HotkeyEvents to Actions.

Decoupled routing layer that translates hotkey events into the
appropriate Action enum members based on the current configuration.
"""

import logging
import threading
from typing import Optional

from src.models.actions import Action
from src.models.events import HotkeyEvent, KeyEventType
from src.config.settings import Settings

logger = logging.getLogger(__name__)


class ActionRouter:
    """Routes hotkey events to their configured actions.

    Thread-safe: the hotkey→action mapping is updated atomically
    on config reload.
    """

    def __init__(self, settings: Settings):
        self._lock = threading.Lock()
        self._hotkey_to_action: dict[str, Action] = {}
        self.update_mappings(settings)

    def update_mappings(self, settings: Settings) -> None:
        """Atomically update the hotkey→action mappings.

        Args:
            settings: The new validated Settings object.
        """
        new_map = dict(settings.hotkeys)
        with self._lock:
            self._hotkey_to_action = new_map
        logger.debug("Action mappings updated: %d hotkeys", len(new_map))

    def resolve(self, event: HotkeyEvent) -> Optional[Action]:
        """Resolve a hotkey event to its configured action.

        Args:
            event: The hotkey event from the keyboard hook.

        Returns:
            The Action to execute, or None if:
            - The event is a KEY_UP (actions fire on DOWN only).
            - The event is an autorepeat (filtered).
            - The hotkey has no configured action.
        """
        # Only fire on key-down, not key-up
        if event.event_type != KeyEventType.DOWN:
            return None

        # Filter autorepeat
        if event.is_autorepeat:
            return None

        with self._lock:
            action = self._hotkey_to_action.get(event.hotkey_name)

        if action is None:
            logger.debug(
                "No action mapped for %s", event.hotkey_name
            )
        return action

    @property
    def mapped_keys(self) -> frozenset[str]:
        """Return the set of currently mapped hotkey names."""
        with self._lock:
            return frozenset(self._hotkey_to_action.keys())
