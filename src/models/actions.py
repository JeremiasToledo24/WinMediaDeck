"""Closed set of valid media/system actions.

Security: This enum is the trust boundary for action validation.
Any action string not present in this enum is rejected immediately
at config parsing time — never reaching MediaController.
"""

from enum import Enum, unique


@unique
class Action(Enum):
    """Enumeration of all valid actions WinMediaDeck can execute."""

    VOLUME_DOWN = "volume_down"
    VOLUME_UP = "volume_up"
    MUTE = "mute"
    PREVIOUS = "previous"
    PLAY_PAUSE = "play_pause"
    NEXT = "next"
    STOP = "stop"
    CALCULATOR = "calculator"
    BROWSER = "browser"
    MEDIA_SELECT = "media_select"
    MAIL = "mail"
    TOGGLE_PAUSE = "toggle_pause"

    @classmethod
    def from_string(cls, value: str) -> "Action":
        """Convert a string to an Action, raising ValueError if invalid.

        Args:
            value: The action string from config (e.g. "volume_up").

        Returns:
            The corresponding Action enum member.

        Raises:
            ValueError: If value is not a recognised action.
        """
        try:
            return cls(value)
        except ValueError:
            valid = ", ".join(sorted(a.value for a in cls))
            raise ValueError(
                f"Unknown action '{value}'. Valid actions: {valid}"
            )
