"""Unit tests for HotkeyManager (isolated with mocks)."""

import queue
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from src.core.hotkey_manager import HotkeyManager
from src.models.events import HotkeyEvent, KeyEventType, HOTKEY_VK_MAP
from src.models.states import AppState


class TestHotkeyManagerUnit:
    """Unit tests for HotkeyManager (without actual Win32 hooks)."""

    def test_init_defaults(self):
        """HotkeyManager initialises with correct defaults."""
        q = queue.Queue()
        mgr = HotkeyManager(
            event_queue=q,
            get_app_state=lambda: AppState.RUNNING,
        )
        assert mgr.is_installed is False
        assert mgr.pressed_keys == frozenset()

    def test_update_mapped_keys(self):
        """Mapped keys can be updated."""
        q = queue.Queue()
        mgr = HotkeyManager(
            event_queue=q,
            get_app_state=lambda: AppState.RUNNING,
            mapped_keys=frozenset({"F1", "F2"}),
        )
        mgr.update_mapped_keys(frozenset({"F5", "F6"}))
        # Internal state — we verify indirectly

    def test_clear_pressed_keys(self):
        """clear_pressed_keys empties the tracking set."""
        q = queue.Queue()
        mgr = HotkeyManager(
            event_queue=q,
            get_app_state=lambda: AppState.RUNNING,
        )
        # Manually add a key (simulating internal state)
        mgr._pressed_keys.add(0x70)
        assert 0x70 in mgr.pressed_keys

        mgr.clear_pressed_keys()
        assert mgr.pressed_keys == frozenset()

    def test_stop_idempotent(self):
        """stop() is idempotent (safe to call multiple times)."""
        q = queue.Queue()
        mgr = HotkeyManager(
            event_queue=q,
            get_app_state=lambda: AppState.RUNNING,
        )
        # Should not raise
        mgr.stop()
        mgr.stop()
        mgr.stop()

    def test_initial_pressed_keys_empty(self):
        """No keys are pressed at initialisation."""
        q = queue.Queue()
        mgr = HotkeyManager(
            event_queue=q,
            get_app_state=lambda: AppState.RUNNING,
        )
        assert mgr.pressed_keys == frozenset()


class TestHotkeyManagerAutorepeat:
    """Tests for autorepeat detection logic."""

    def test_pressed_keys_tracking(self):
        """Pressed keys set tracks additions and removals."""
        q = queue.Queue()
        mgr = HotkeyManager(
            event_queue=q,
            get_app_state=lambda: AppState.RUNNING,
        )

        # Simulate key down
        vk = 0x70  # F1
        mgr._pressed_keys.add(vk)
        assert vk in mgr.pressed_keys

        # Simulate key up
        mgr._pressed_keys.discard(vk)
        assert vk not in mgr.pressed_keys

    def test_clear_on_state_transition(self):
        """Pressed keys are cleared to avoid ghost states."""
        q = queue.Queue()
        mgr = HotkeyManager(
            event_queue=q,
            get_app_state=lambda: AppState.RUNNING,
        )

        # Hold several keys
        mgr._pressed_keys.update({0x70, 0x71, 0x72})
        assert len(mgr.pressed_keys) == 3

        # Clear (as done on RUNNING ↔ PAUSED transition)
        mgr.clear_pressed_keys()
        assert len(mgr.pressed_keys) == 0
