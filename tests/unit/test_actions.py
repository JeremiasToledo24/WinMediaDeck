"""Unit tests for Action enum."""

import pytest

from src.models.actions import Action


class TestActionEnum:
    """Tests for the Action enum (closed set)."""

    def test_all_actions_defined(self):
        """Verify all 12 actions exist."""
        expected = {
            "volume_down", "volume_up", "mute",
            "previous", "play_pause", "next", "stop",
            "calculator", "browser", "media_select",
            "mail", "toggle_pause",
        }
        actual = {a.value for a in Action}
        assert actual == expected

    def test_from_string_valid(self):
        """Valid action strings resolve correctly."""
        assert Action.from_string("volume_up") == Action.VOLUME_UP
        assert Action.from_string("play_pause") == Action.PLAY_PAUSE
        assert Action.from_string("toggle_pause") == Action.TOGGLE_PAUSE

    def test_from_string_invalid(self):
        """Invalid action strings raise ValueError."""
        with pytest.raises(ValueError, match="Unknown action 'exec_command'"):
            Action.from_string("exec_command")

    def test_from_string_empty(self):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="Unknown action"):
            Action.from_string("")

    def test_from_string_case_sensitive(self):
        """Action matching is case-sensitive."""
        with pytest.raises(ValueError):
            Action.from_string("VOLUME_UP")

    def test_from_string_injection_attempt(self):
        """Injection-style strings are rejected."""
        with pytest.raises(ValueError):
            Action.from_string("os.system('rm -rf /')")

    def test_enum_uniqueness(self):
        """All action values are unique."""
        values = [a.value for a in Action]
        assert len(values) == len(set(values))

    def test_action_count(self):
        """Exactly 12 actions defined."""
        assert len(Action) == 12
