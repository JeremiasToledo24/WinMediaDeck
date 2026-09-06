"""Unit tests for SettingsWindow, autostart toggle, and safe shutdown mechanism."""

import json
import pytest
import threading
import tkinter as tk
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.ui.settings_window import (
    SettingsWindow,
    _ACTION_LABELS,
    _LABEL_TO_ACTION,
    _UNASSIGNED,
    _FKEYS,
)
from src.platform.windows.mutex import (
    create_quit_event,
    signal_quit_event,
    wait_quit_event,
    close_event,
)
from src.ui.tray_app import TrayApp


@pytest.fixture(scope="module")
def tk_root():
    """Shared hidden Tk root for widget instantiation."""
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def custom_config(tmp_path):
    """Create a custom config file with modified hotkeys and autostart."""
    config_data = {
        "schema_version": 1,
        "enabled": True,
        "osd": {
            "enabled": False,
            "duration_ms": 2500,
        },
        "hotkeys": {
            "F1": "play_pause",
            "F2": "mute",
            "F3": "browser",
        },
    }
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(config_data), encoding="utf-8")
    return config_file


class TestSettingsWindowHeadless:
    """Headless tests for SettingsWindow logic, mapping, and autostart."""

    def test_load_config_dict(self, custom_config):
        """SettingsWindow loads custom config accurately."""
        window = SettingsWindow(config_path=custom_config)
        loaded = window._load_config_dict()
        assert loaded["hotkeys"]["F1"] == "play_pause"
        assert loaded["hotkeys"]["F2"] == "mute"
        assert loaded["hotkeys"]["F3"] == "browser"
        assert loaded["osd"]["enabled"] is False
        assert loaded["osd"]["duration_ms"] == 2500

    def test_collect_config_preserves_custom_values(self, tk_root, custom_config):
        """_collect_config correctly extracts UI selections."""
        window = SettingsWindow(config_path=custom_config)
        window._root = tk_root
        config_dict = window._load_config_dict()
        window._build_ui(config_dict)

        # Verify initial UI state matches custom config
        assert window._hotkey_vars["F1"].get() == _ACTION_LABELS["play_pause"]
        assert window._hotkey_vars["F2"].get() == _ACTION_LABELS["mute"]
        assert window._hotkey_vars["F3"].get() == _ACTION_LABELS["browser"]
        assert window._hotkey_vars["F4"].get() == _UNASSIGNED

        # Modify F4 to volume_up
        window._hotkey_vars["F4"].set(_ACTION_LABELS["volume_up"])
        window._combos["F4"].set(_ACTION_LABELS["volume_up"])

        collected = window._collect_config()
        assert collected["hotkeys"]["F1"] == "play_pause"
        assert collected["hotkeys"]["F2"] == "mute"
        assert collected["hotkeys"]["F3"] == "browser"
        assert collected["hotkeys"]["F4"] == "volume_up"
        assert collected["osd"]["enabled"] is False
        assert collected["osd"]["duration_ms"] == 2500

    def test_reload_from_disk(self, tk_root, custom_config):
        """_reload_from_disk refreshes UI with changes made on disk."""
        window = SettingsWindow(config_path=custom_config)
        window._root = tk_root
        config_dict = window._load_config_dict()
        window._build_ui(config_dict)

        # Initially F1 is play_pause
        assert window._hotkey_vars["F1"].get() == _ACTION_LABELS["play_pause"]

        # External edit to config
        new_data = window._load_config_dict()
        new_data["hotkeys"]["F1"] = "calculator"
        custom_config.write_text(json.dumps(new_data), encoding="utf-8")

        # Reload
        window._reload_from_disk()

        # Now F1 must reflect calculator
        assert window._hotkey_vars["F1"].get() == _ACTION_LABELS["calculator"]
        assert window._combos["F1"].get() == _ACTION_LABELS["calculator"]

    @patch("src.ui.settings_window.AutostartManager")
    def test_save_autostart_sync(self, mock_autostart_cls, tk_root, custom_config):
        """Saving with autostart enabled invokes AutostartManager.enable()."""
        mock_mgr = MagicMock()
        mock_mgr.is_enabled.return_value = False
        mock_autostart_cls.return_value = mock_mgr

        window = SettingsWindow(config_path=custom_config)
        window._root = tk_root
        config_dict = window._load_config_dict()
        window._build_ui(config_dict)

        # Check autostart checkbox
        window._autostart_var.set(True)

        with patch.object(window, "_on_close"):
            window._save()

        mock_mgr.enable.assert_called_once()

    def test_theme_load_and_collect(self, tk_root, tmp_path):
        """SettingsWindow loads theme and collects it in config."""
        config_data = {
            "schema_version": 1,
            "theme": "light",
            "hotkeys": {},
        }
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(config_data), encoding="utf-8")

        window = SettingsWindow(config_path=cfg_file)
        window._root = tk_root
        config_dict = window._load_config_dict()
        window._build_ui(config_dict)

        assert window._theme_var.get() == "☀️ Claro"
        collected = window._collect_config()
        assert collected["theme"] == "light"

        # Change to dark
        window._theme_var.set("🌙 Oscuro")
        collected_dark = window._collect_config()
        assert collected_dark["theme"] == "dark"

    def test_apply_theme_switches_palette(self, tk_root, custom_config):
        """_apply_theme dynamically updates colors on registered widgets."""
        window = SettingsWindow(config_path=custom_config)
        window._root = tk_root
        config_dict = window._load_config_dict()
        window._build_ui(config_dict)

        # Switch to light
        window._apply_theme("light")
        assert window._current_theme == "light"

        # Switch to dark
        window._apply_theme("dark")
        assert window._current_theme == "dark"

    def test_landing_v3_color_system_integrity(self):
        """THEMES and tray states adhere strictly to landing_v3.html tokens."""
        from src.ui.settings_window import THEMES
        from src.ui.tray_app import _STATE_COLORS
        from src.models.states import AppState

        # Light theme matches landing_v3.html tokens
        assert THEMES["light"]["bg"] == "#ffffff"        # --bg
        assert THEMES["light"]["card_bg"] == "#f2f1ed"   # --panel
        assert THEMES["light"]["fg"] == "#1b1b18"        # --ink
        assert THEMES["light"]["fg_dim"] == "#55534c"    # --ink-soft
        assert THEMES["light"]["accent"] == "#3c6e52"    # --active (forest green)
        assert THEMES["light"]["warning"] == "#9a7b1f"   # --paused
        assert THEMES["light"]["danger"] == "#a13d3d"    # --blocked
        assert THEMES["light"]["link"] == "#1c5c8a"      # --link

        # Dark theme matches landing_v3.html dark tokens
        assert THEMES["dark"]["bg"] == "#1b1b18"         # --ink / topstrip / logo
        assert THEMES["dark"]["bg_field"] == "#1c1c1a"   # pre code background
        assert THEMES["dark"]["fg"] == "#f2f1ed"         # --panel as light text

        # Tray state colors match landing_v3.html
        assert _STATE_COLORS[AppState.RUNNING][1] == "#3c6e52"  # --active
        assert _STATE_COLORS[AppState.PAUSED][1] == "#9a7b1f"   # --paused
        assert _STATE_COLORS[AppState.BLOCKED][1] == "#a13d3d"  # --blocked


class TestQuitEventIPC:
    """Tests for the Win32 IPC quit event mechanism."""

    def test_quit_event_lifecycle(self):
        """Create, signal, wait, and close quit event."""
        handle = create_quit_event()
        if not handle:
            pytest.skip("Win32 CreateEventW not available in this environment")

        try:
            # Initially not signaled
            assert not wait_quit_event(handle, timeout_ms=50)

            # Signal from another call
            signaled = signal_quit_event()
            assert signaled is True

            # Wait should now return True
            assert wait_quit_event(handle, timeout_ms=500) is True
        finally:
            close_event(handle)


class TestTrayAppShutdown:
    """Tests for safe shutdown in TrayApp."""

    def test_shutdown_from_same_thread_does_not_deadlock(self):
        """Calling shutdown from the tray thread does not raise RuntimeError."""
        app = TrayApp()
        app._started = True
        app._thread = threading.current_thread()

        # Should complete immediately without calling join() on current_thread
        app.shutdown()
        assert app._started is False
        assert app._thread is None

    def test_tray_app_on_about_wired(self):
        """TrayApp accepts and executes on_about callback."""
        called = threading.Event()

        def _on_about():
            called.set()

        app = TrayApp(on_about=_on_about)
        assert app._on_about is _on_about

        app._handle_about()
        assert called.wait(timeout=2.0) is True


class TestAboutDialogHeadless:
    """Headless unit tests for the discrete About dialog."""

    def test_about_dialog_construction_and_content(self, tk_root):
        """_build_about_dialog correctly renders version, author, and github repository link."""
        from src import __version__
        from src.ui.settings_window import THEMES

        dlg = SettingsWindow._build_about_dialog(tk_root, THEMES["dark"], is_standalone=False)
        try:
            assert dlg.title() == "Acerca de WinMediaDeck"

            # Search all labels inside dlg for text content
            texts = []

            def _find_labels(widget):
                for child in widget.winfo_children():
                    if isinstance(child, tk.Label):
                        texts.append(child.cget("text"))
                    _find_labels(child)

            _find_labels(dlg)

            # Ensure version, author, and link text are present
            assert any(f"v{__version__}" in t for t in texts)
            assert any("Jeremías Toledo" in t for t in texts)
            assert any("JeremiasToledo24/WinMediaDeck" in t for t in texts)
            assert any("Licencia MIT" in t for t in texts)
        finally:
            dlg.destroy()

    def test_settings_window_renders_about_button(self, tk_root, custom_config):
        """SettingsWindow action bar renders discrete Acerca de button."""
        window = SettingsWindow(config_path=custom_config)
        window._root = tk_root
        config_dict = window._load_config_dict()
        window._build_ui(config_dict)

        # Search buttons for "Acerca de"
        buttons = []

        def _find_buttons(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Button):
                    buttons.append(child.cget("text"))
                _find_buttons(child)

        _find_buttons(tk_root)

        assert any("Acerca de" in btn for btn in buttons)

    @patch("pystray.Icon")
    @patch("pystray.Menu")
    def test_about_is_last_in_options_list(self, mock_menu_cls, mock_icon_cls):
        """In TrayApp, Acerca de is placed at the end of the options list before Quit."""
        app = TrayApp(
            on_open_settings=lambda: None,
            on_open_config=lambda: None,
            on_toggle_autostart=lambda: None,
            on_toggle_theme=lambda: None,
            on_diagnostic=lambda: None,
            on_about=lambda: None,
            on_quit=lambda: None,
        )
        mock_icon_inst = MagicMock()
        mock_icon_cls.return_value = mock_icon_inst
        mock_icon_inst.run = MagicMock()

        app._tray_main()

        call_args = mock_menu_cls.call_args[0]
        labels = [getattr(item, "text", str(item)) for item in call_args]

        idx_diag = next(i for i, l in enumerate(labels) if "Diagnóstico" in l)
        idx_about = next(i for i, l in enumerate(labels) if "Acerca de" in l)
        idx_quit = next(i for i, l in enumerate(labels) if "Salir" in l)

        # Acerca de must be after Diagnóstico (last in options list) and before Salir
        assert idx_about > idx_diag
        assert idx_about < idx_quit

