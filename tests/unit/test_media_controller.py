"""Unit tests for MediaController."""

import pytest
from unittest.mock import patch, MagicMock

from src.core.media_controller import MediaController
from src.models.actions import Action


class TestMediaController:
    """Tests for MediaController dispatch."""

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_volume_up(self, mock_send):
        """VOLUME_UP dispatches the correct VK."""
        ctrl = MediaController()
        result = ctrl.execute(Action.VOLUME_UP)
        assert result is True
        mock_send.assert_called_once()
        # VK_VOLUME_UP = 0xAF
        args = mock_send.call_args
        assert args[0][0] == 0xAF

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_volume_down(self, mock_send):
        """VOLUME_DOWN dispatches the correct VK."""
        ctrl = MediaController()
        ctrl.execute(Action.VOLUME_DOWN)
        args = mock_send.call_args
        assert args[0][0] == 0xAE  # VK_VOLUME_DOWN

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_mute(self, mock_send):
        """MUTE dispatches the correct VK."""
        ctrl = MediaController()
        ctrl.execute(Action.MUTE)
        args = mock_send.call_args
        assert args[0][0] == 0xAD  # VK_VOLUME_MUTE

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_play_pause(self, mock_send):
        """PLAY_PAUSE dispatches the correct VK."""
        ctrl = MediaController()
        ctrl.execute(Action.PLAY_PAUSE)
        args = mock_send.call_args
        assert args[0][0] == 0xB3  # VK_MEDIA_PLAY_PAUSE

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_next(self, mock_send):
        """NEXT dispatches the correct VK."""
        ctrl = MediaController()
        ctrl.execute(Action.NEXT)
        args = mock_send.call_args
        assert args[0][0] == 0xB0  # VK_MEDIA_NEXT_TRACK

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_previous(self, mock_send):
        """PREVIOUS dispatches the correct VK."""
        ctrl = MediaController()
        ctrl.execute(Action.PREVIOUS)
        args = mock_send.call_args
        assert args[0][0] == 0xB1  # VK_MEDIA_PREV_TRACK

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_stop(self, mock_send):
        """STOP dispatches the correct VK."""
        ctrl = MediaController()
        ctrl.execute(Action.STOP)
        args = mock_send.call_args
        assert args[0][0] == 0xB2  # VK_MEDIA_STOP

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_execute_calculator(self, mock_send):
        """CALCULATOR dispatches the correct VK."""
        ctrl = MediaController()
        ctrl.execute(Action.CALCULATOR)
        args = mock_send.call_args
        assert args[0][0] == 0xB6  # VK_LAUNCH_APP1

    def test_execute_toggle_pause_is_meta(self):
        """TOGGLE_PAUSE returns True without calling SendInput."""
        ctrl = MediaController()
        with patch("src.core.media_controller.send_key_press") as mock_send:
            result = ctrl.execute(Action.TOGGLE_PAUSE)
            assert result is True
            mock_send.assert_not_called()

    @patch("src.core.media_controller.send_key_press", return_value=False)
    def test_on_blocked_callback(self, mock_send):
        """on_blocked is called when SendInput fails."""
        blocked_called = []
        ctrl = MediaController(on_blocked=lambda: blocked_called.append(True))
        ctrl.execute(Action.VOLUME_UP)
        assert len(blocked_called) == 1

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_on_blocked_not_called_on_success(self, mock_send):
        """on_blocked is NOT called when SendInput succeeds."""
        blocked_called = []
        ctrl = MediaController(on_blocked=lambda: blocked_called.append(True))
        ctrl.execute(Action.VOLUME_UP)
        assert len(blocked_called) == 0

    @patch("src.core.media_controller.send_key_press", return_value=True)
    def test_extended_key_flag(self, mock_send):
        """All media keys are sent with extended=True."""
        ctrl = MediaController()
        ctrl.execute(Action.VOLUME_UP)
        args = mock_send.call_args
        assert args[1].get("extended", args[0][1] if len(args[0]) > 1 else True) is True
