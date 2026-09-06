"""Event and hotkey data models for the keyboard hook pipeline.

These models flow through the event queue from the hook callback
to the event dispatcher — never carrying raw keystroke data beyond
the configured F1-F12 range (privacy by design).
"""

from dataclasses import dataclass, field
from enum import Enum, unique
from typing import Optional
import time


# Virtual key codes for F1-F12 (0x70 - 0x7B)
VK_F1 = 0x70
VK_F12 = 0x7B

# All valid F-key names mapped to their virtual key codes
HOTKEY_VK_MAP: dict[str, int] = {
    f"F{i}": VK_F1 + (i - 1) for i in range(1, 13)
}

# Reverse lookup: VK code → hotkey name
VK_HOTKEY_MAP: dict[int, str] = {v: k for k, v in HOTKEY_VK_MAP.items()}

# Set of all valid VK codes for quick membership testing in the hook
VALID_VK_CODES: frozenset[int] = frozenset(HOTKEY_VK_MAP.values())


@unique
class KeyEventType(Enum):
    """Type of keyboard event received from the low-level hook."""
    DOWN = "down"
    UP = "up"


@dataclass(frozen=True, slots=True)
class HotkeyEvent:
    """Immutable event produced by the keyboard hook callback.

    Attributes:
        hotkey_name: The F-key name (e.g. "F5").
        vk_code: The Windows virtual key code (0x70-0x7B).
        event_type: Whether this is a key down or key up event.
        timestamp: Monotonic timestamp when the event was captured.
        is_autorepeat: True if this is a held-key repeat (should be filtered).
    """
    hotkey_name: str
    vk_code: int
    event_type: KeyEventType
    timestamp: float = field(default_factory=time.monotonic)
    is_autorepeat: bool = False
