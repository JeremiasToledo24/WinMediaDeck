"""Unit tests for ActionRouter."""

import pytest

from src.core.action_router import ActionRouter
from src.config.settings import parse_config, _default_config_dict
from src.models.actions import Action
from src.models.events import HotkeyEvent, KeyEventType


def _make_settings(**overrides):
    """Create settings with optional overrides."""
    data = _default_config_dict()
    data.update(overrides)
    return parse_config(data)


def _make_event(
    hotkey: str = "F5",
    event_type: KeyEventType = KeyEventType.DOWN,
    is_autorepeat: bool = False,
) -> HotkeyEvent:
    """Create a HotkeyEvent for testing."""
    from src.models.events import HOTKEY_VK_MAP
    return HotkeyEvent(
        hotkey_name=hotkey,
        vk_code=HOTKEY_VK_MAP[hotkey],
        event_type=event_type,
        is_autorepeat=is_autorepeat,
    )


class TestActionRouter:
    """Tests for ActionRouter."""

    def test_resolve_mapped_key_down(self):
        """Mapped key DOWN resolves to the correct action."""
        settings = _make_settings()
        router = ActionRouter(settings)

        action = router.resolve(_make_event("F5", KeyEventType.DOWN))
        assert action == Action.PLAY_PAUSE

    def test_resolve_key_up_returns_none(self):
        """KEY_UP events always return None (actions fire on DOWN only)."""
        settings = _make_settings()
        router = ActionRouter(settings)

        action = router.resolve(_make_event("F5", KeyEventType.UP))
        assert action is None

    def test_resolve_autorepeat_returns_none(self):
        """Autorepeat events are filtered (return None)."""
        settings = _make_settings()
        router = ActionRouter(settings)

        action = router.resolve(
            _make_event("F5", KeyEventType.DOWN, is_autorepeat=True)
        )
        assert action is None

    def test_resolve_unmapped_key(self):
        """Unmapped key returns None."""
        settings = parse_config({
            "schema_version": 1,
            "hotkeys": {"F1": "volume_up"},
        })
        router = ActionRouter(settings)

        action = router.resolve(_make_event("F5"))
        assert action is None

    def test_update_mappings(self):
        """Updating mappings changes resolution results."""
        settings1 = parse_config({
            "schema_version": 1,
            "hotkeys": {"F5": "play_pause"},
        })
        settings2 = parse_config({
            "schema_version": 1,
            "hotkeys": {"F5": "mute"},
        })

        router = ActionRouter(settings1)
        assert router.resolve(_make_event("F5")) == Action.PLAY_PAUSE

        router.update_mappings(settings2)
        assert router.resolve(_make_event("F5")) == Action.MUTE

    def test_mapped_keys_property(self):
        """mapped_keys returns the correct set of keys."""
        settings = parse_config({
            "schema_version": 1,
            "hotkeys": {"F1": "volume_up", "F2": "volume_down"},
        })
        router = ActionRouter(settings)
        assert router.mapped_keys == frozenset({"F1", "F2"})

    def test_all_default_keys_mapped(self):
        """All F1-F12 keys resolve to actions with default config."""
        settings = _make_settings()
        router = ActionRouter(settings)

        for i in range(1, 13):
            key = f"F{i}"
            action = router.resolve(_make_event(key))
            assert action is not None, f"{key} should have a mapped action"

    def test_toggle_pause_resolves(self):
        """F12 (toggle_pause) resolves correctly."""
        settings = _make_settings()
        router = ActionRouter(settings)

        action = router.resolve(_make_event("F12"))
        assert action == Action.TOGGLE_PAUSE
