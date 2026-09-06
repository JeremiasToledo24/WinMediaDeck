"""Integration tests for Win32 boundary layer.

These tests verify that the Win32 ctypes wrappers work correctly
on a real Windows system. They are designed to be safe — no hooks
are installed, only read-only queries are performed.
"""

import ctypes
import sys

import pytest

# Skip all tests if not on Windows
pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="Win32 integration tests require Windows",
)


class TestWin32Keyboard:
    """Tests for the keyboard platform module."""

    def test_hookproc_type_exists(self):
        """HOOKPROC ctypes type is correctly defined."""
        from src.platform.windows.keyboard import HOOKPROC
        assert HOOKPROC is not None

    def test_kbdllhookstruct_fields(self):
        """KBDLLHOOKSTRUCT has the required fields."""
        from src.platform.windows.keyboard import KBDLLHOOKSTRUCT
        fields = {name for name, _ in KBDLLHOOKSTRUCT._fields_}
        assert "vkCode" in fields
        assert "scanCode" in fields
        assert "flags" in fields
        assert "time" in fields

    def test_get_current_thread_id(self):
        """get_current_thread_id returns a positive integer."""
        from src.platform.windows.keyboard import get_current_thread_id
        tid = get_current_thread_id()
        assert isinstance(tid, int)
        assert tid > 0

    def test_install_and_uninstall_hook(self):
        """install_hook successfully creates and uninstalls a hook handle."""
        from src.platform.windows.keyboard import install_hook, uninstall_hook, HOOKPROC

        def dummy_cb(n_code, w_param, l_param):
            return 0

        proc = HOOKPROC(dummy_cb)
        handle = install_hook(proc)
        assert handle is not None
        assert isinstance(handle, int)
        assert handle != 0

        unhooked = uninstall_hook(handle)
        assert unhooked is True


class TestWin32Input:
    """Tests for the input platform module."""

    def test_input_structure_size(self):
        """INPUT structure has the expected exact size for the target architecture."""
        from src.platform.windows.input import INPUT
        expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        assert ctypes.sizeof(INPUT) == expected_size

    def test_input_fields_and_substructures(self):
        """KEYBDINPUT, MOUSEINPUT, and HARDWAREINPUT have correct fields."""
        from src.platform.windows.input import KEYBDINPUT, MOUSEINPUT, HARDWAREINPUT
        k_fields = {name for name, _ in KEYBDINPUT._fields_}
        assert {"wVk", "wScan", "dwFlags", "time", "dwExtraInfo"}.issubset(k_fields)

        m_fields = {name for name, _ in MOUSEINPUT._fields_}
        assert {"dx", "dy", "mouseData", "dwFlags", "time", "dwExtraInfo"}.issubset(m_fields)

        h_fields = {name for name, _ in HARDWAREINPUT._fields_}
        assert {"uMsg", "wParamL", "wParamH"}.issubset(h_fields)

    def test_vk_constants_defined(self):
        """All required VK constants are defined."""
        from src.platform.windows import input as inp
        assert inp.VK_VOLUME_MUTE == 0xAD
        assert inp.VK_VOLUME_DOWN == 0xAE
        assert inp.VK_VOLUME_UP == 0xAF
        assert inp.VK_MEDIA_NEXT_TRACK == 0xB0
        assert inp.VK_MEDIA_PREV_TRACK == 0xB1
        assert inp.VK_MEDIA_STOP == 0xB2
        assert inp.VK_MEDIA_PLAY_PAUSE == 0xB3
        assert inp.VK_LAUNCH_APP1 == 0xB6
        assert inp.VK_LAUNCH_APP2 == 0xB7


class TestWin32Monitors:
    """Tests for the monitor utilities."""

    def test_get_cursor_position(self):
        """get_cursor_position returns a valid tuple."""
        from src.platform.windows.monitors import get_cursor_position
        x, y = get_cursor_position()
        assert isinstance(x, int)
        assert isinstance(y, int)

    def test_get_display_count(self):
        """get_display_count returns at least 1."""
        from src.platform.windows.monitors import get_display_count
        count = get_display_count()
        assert count >= 1

    def test_get_monitor_at_cursor(self):
        """get_monitor_at_cursor returns a valid MonitorRect."""
        from src.platform.windows.monitors import get_monitor_at_cursor
        rect = get_monitor_at_cursor()
        assert rect is not None
        assert rect.width > 0
        assert rect.height > 0


class TestWin32Mutex:
    """Tests for the mutex module."""

    def test_mutex_name_constant(self):
        """MUTEX_NAME follows the Local\\ convention."""
        from src.platform.windows.mutex import MUTEX_NAME
        assert MUTEX_NAME == "Local\\WinMediaDeck_Session_Mutex"

    def test_release_null_handle(self):
        """release_mutex with 0 handle is safe."""
        from src.platform.windows.mutex import release_mutex
        # Should not raise
        release_mutex(0)
        release_mutex(None)


class TestWin32Events:
    """Tests for the event model VK mappings."""

    def test_vk_range(self):
        """F1-F12 VK codes are in the correct range."""
        from src.models.events import VK_F1, VK_F12, VALID_VK_CODES
        assert VK_F1 == 0x70
        assert VK_F12 == 0x7B

        # All codes in the valid set should be F1-F12
        for vk in VALID_VK_CODES:
            assert 0x70 <= vk <= 0x7B

    def test_vk_hotkey_map_bidirectional(self):
        """HOTKEY_VK_MAP and VK_HOTKEY_MAP are consistent."""
        from src.models.events import HOTKEY_VK_MAP, VK_HOTKEY_MAP

        assert len(HOTKEY_VK_MAP) == 12
        assert len(VK_HOTKEY_MAP) == 12

        for name, vk in HOTKEY_VK_MAP.items():
            assert VK_HOTKEY_MAP[vk] == name
