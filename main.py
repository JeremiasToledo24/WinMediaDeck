"""WinMediaDeck — Main entry point.

Orchestrates: CLI parsing, Mutex, Config, State Machine,
Event Dispatcher, Hook, OSD, Tray, and Safe Shutdown.
"""

import argparse
import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from typing import Optional

# Ensure project root is on sys.path for direct execution
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.models.actions import Action
from src.models.events import HotkeyEvent
from src.models.states import AppState
from src.config.settings import (
    ConfigManager,
    ConfigurationError,
    Settings,
    get_config_path,
    write_config_atomic,
)
from src.config.watcher import ConfigWatcher
from src.core.action_router import ActionRouter
from src.core.hotkey_manager import HotkeyManager
from src.core.media_controller import MediaController
from src.core.autostart import AutostartManager
from src.core.system_detector import detect_system
from src.core.compatibility import analyze_compatibility, format_report
from src.platform.windows.mutex import (
    acquire_mutex,
    release_mutex,
    AlreadyRunningError,
    MutexError,
    create_quit_event,
    signal_quit_event,
    wait_quit_event,
    close_event,
)
from src import __version__
from src.ui.osd import OSDService, _set_dpi_awareness
from src.ui.tray_app import TrayApp
from src.ui.settings_window import SettingsWindow

logger = logging.getLogger("WinMediaDeck")


class LifecycleManager:
    """Orchestrates the full application lifecycle.

    Manages startup, state transitions, event dispatch, and
    guaranteed safe shutdown (idempotent).
    """

    def __init__(self, debug: bool = False):
        self._debug = debug
        self._state = AppState.STARTING
        self._state_lock = threading.Lock()
        self._is_stopped = False
        self._shutdown_lock = threading.Lock()

        # Components (initialized during startup)
        self._mutex_handle: Optional[int] = None
        self._quit_event: Optional[int] = None
        self._quit_thread: Optional[threading.Thread] = None
        self._config_manager: Optional[ConfigManager] = None
        self._config_watcher: Optional[ConfigWatcher] = None
        self._action_router: Optional[ActionRouter] = None
        self._hotkey_manager: Optional[HotkeyManager] = None
        self._media_controller: Optional[MediaController] = None
        self._osd_service: Optional[OSDService] = None
        self._tray_app: Optional[TrayApp] = None
        self._autostart_manager: Optional[AutostartManager] = None

        # Event queues
        self._hotkey_queue: queue.Queue[HotkeyEvent] = queue.Queue(maxsize=256)
        self._dispatcher_thread: Optional[threading.Thread] = None
        self._dispatcher_stop = threading.Event()

        # Main thread event for blocking
        self._main_stop = threading.Event()

    @property
    def state(self) -> AppState:
        """Current application state (thread-safe)."""
        with self._state_lock:
            return self._state

    def _set_state(self, new_state: AppState) -> None:
        """Transition to a new state with logging and tray update."""
        with self._state_lock:
            old = self._state
            self._state = new_state
        logger.info("State: %s → %s", old.value, new_state.value)
        if self._tray_app:
            self._tray_app.update_state(new_state)

    def _get_state(self) -> AppState:
        """Get current state (callable reference for HotkeyManager)."""
        return self.state

    def _quit_listener_main(self) -> None:
        """Background listener that monitors the named quit event."""
        while not self._main_stop.is_set():
            try:
                if self._quit_event and wait_quit_event(self._quit_event, timeout_ms=500):
                    logger.info("Quit event signaled from external process. Shutting down...")
                    self.shutdown()
                    break
            except Exception:
                break

    def run(self) -> int:
        """Run the full application lifecycle.

        Returns:
            Exit code (0 = success, 1 = error, 2 = already running).
        """
        # Install signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        sys.excepthook = self._exception_handler

        try:
            return self._startup()
        except Exception:
            logger.exception("Unhandled exception during startup")
            self.shutdown()
            return 1

    def _startup(self) -> int:
        """Execute the startup sequence."""
        self._set_state(AppState.STARTING)

        # 1. Acquire mutex
        try:
            self._mutex_handle = acquire_mutex()
        except AlreadyRunningError as e:
            print(str(e), file=sys.stderr)
            return 2
        except MutexError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        # Start quit event IPC listener
        try:
            self._quit_event = create_quit_event()
            if self._quit_event:
                self._quit_thread = threading.Thread(
                    target=self._quit_listener_main,
                    name="WinMediaDeck-QuitListener",
                    daemon=True,
                )
                self._quit_thread.start()
        except Exception as e:
            logger.debug("Could not start quit event listener: %s", e)

        self._set_state(AppState.VALIDATING)

        # 2. Load config
        try:
            self._config_manager = ConfigManager()
            settings = self._config_manager.load()
        except ConfigurationError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            self._set_state(AppState.FAILED)
            self.shutdown()
            return 1

        # 3. Initialize components
        try:
            self._init_components(settings)
        except Exception:
            logger.exception("Failed to initialize components")
            self._set_state(AppState.FAILED)
            self.shutdown()
            return 1

        self._set_state(AppState.READY)

        # 4. Start components
        try:
            self._start_components(settings)
        except Exception:
            logger.exception("Failed to start components")
            self._set_state(AppState.FAILED)
            self.shutdown()
            return 1

        # 5. Enter active state
        if settings.enabled:
            self._set_state(AppState.RUNNING)
        else:
            self._set_state(AppState.PAUSED)

        # 6. Show startup notification
        if self._tray_app:
            time.sleep(0.5)  # Brief delay to ensure tray icon is visible
            self._tray_app.notify(
                "WinMediaDeck activo",
                "Hotkeys de medios habilitados. Click derecho en el icono para ajustes.",
            )

        # 7. Block main thread until shutdown
        self._start_console_listener()
        logger.info("WinMediaDeck is active. Press 'q' + Enter or Ctrl+C to exit.")
        try:
            while not self._main_stop.wait(timeout=0.5):
                pass
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received from console, shutting down...")
            self.shutdown()

        return 0

    def _init_components(self, settings: Settings) -> None:
        """Initialize all components without starting them."""
        # Action router
        self._action_router = ActionRouter(settings)

        # Media controller
        self._media_controller = MediaController(
            on_blocked=self._on_input_blocked,
        )

        # OSD
        if settings.osd.enabled:
            self._osd_service = OSDService(
                duration_ms=settings.osd.duration_ms,
                theme=settings.theme,
            )

        # Autostart
        self._autostart_manager = AutostartManager()

        # System tray
        self._tray_app = TrayApp(
            on_toggle_pause=self._toggle_pause,
            on_toggle_autostart=self._toggle_autostart,
            on_toggle_theme=self._toggle_theme,
            on_quit=self._request_quit,
            on_open_config=self._open_config,
            on_open_settings=self._open_settings,
            on_diagnostic=self._run_diagnostic,
            get_autostart_state=(
                lambda: self._autostart_manager.is_enabled()
                if self._autostart_manager else False
            ),
            get_theme_state=self._get_theme_state,
            on_about=self._open_about,
        )

        # Hotkey manager
        self._hotkey_manager = HotkeyManager(
            event_queue=self._hotkey_queue,
            get_app_state=self._get_state,
            mapped_keys=self._action_router.mapped_keys,
        )

        # Config watcher
        if self._config_manager:
            self._config_watcher = ConfigWatcher(
                config_dir=self._config_manager.config_path.parent,
                on_change=self._on_config_changed,
            )

    def _start_components(self, settings: Settings) -> None:
        """Start all components in the correct order."""
        # Start OSD
        if self._osd_service:
            self._osd_service.start()

        # Start tray
        if self._tray_app:
            self._tray_app.start(
                initial_state=AppState.RUNNING if settings.enabled else AppState.PAUSED
            )

        # Start event dispatcher
        self._dispatcher_stop.clear()
        self._dispatcher_thread = threading.Thread(
            target=self._event_dispatcher_main,
            name="WinMediaDeck-Dispatcher",
            daemon=True,
        )
        self._dispatcher_thread.start()

        # Start hotkey manager (hook + message pump)
        if self._hotkey_manager:
            self._hotkey_manager.start()

        # Start config watcher
        if self._config_watcher:
            self._config_watcher.start()

    def _event_dispatcher_main(self) -> None:
        """Event dispatcher thread: reads from hotkey queue and routes."""
        logger.debug("Event dispatcher started")

        while not self._dispatcher_stop.is_set():
            try:
                event = self._hotkey_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._dispatch_event(event)
            except Exception:
                logger.exception("Error dispatching event")

        logger.debug("Event dispatcher stopped")

    def _dispatch_event(self, event: HotkeyEvent) -> None:
        """Route a single hotkey event to the appropriate handler."""
        if not self._action_router:
            return

        action = self._action_router.resolve(event)
        if action is None:
            return

        logger.debug("Dispatching action: %s (from %s)", action.value, event.hotkey_name)

        # Handle TOGGLE_PAUSE specially
        if action == Action.TOGGLE_PAUSE:
            self._toggle_pause()
            return

        # Execute the media action
        if self._media_controller:
            success = self._media_controller.execute(action)

            if success:
                # Show OSD
                if self._osd_service and self.state == AppState.RUNNING:
                    self._osd_service.show(action)
            else:
                logger.warning("Action %s failed to execute", action.value)

    def _toggle_pause(self) -> None:
        """Toggle between RUNNING and PAUSED states."""
        current = self.state

        if current == AppState.RUNNING:
            self._set_state(AppState.PAUSED)
            if self._hotkey_manager:
                self._hotkey_manager.clear_pressed_keys()
            logger.info("Application paused")
        elif current == AppState.PAUSED:
            self._set_state(AppState.RUNNING)
            if self._hotkey_manager:
                self._hotkey_manager.clear_pressed_keys()
            logger.info("Application resumed")
        else:
            logger.warning("Cannot toggle pause in state %s", current.value)

    def _toggle_autostart(self) -> None:
        """Toggle autostart on/off."""
        if self._autostart_manager:
            enabled = self._autostart_manager.toggle()
            logger.info("Autostart %s", "enabled" if enabled else "disabled")

    def _toggle_theme(self) -> None:
        """Toggle between dark and light themes."""
        if not self._config_manager:
            return
        current_settings = self._config_manager.settings
        new_theme = "light" if current_settings.theme == "dark" else "dark"
        config_path = self._config_manager.config_path
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["theme"] = new_theme
            write_config_atomic(data, config_path)
            logger.info("Theme toggled to %s", new_theme)
        except Exception:
            logger.exception("Failed to toggle theme")

    def _get_theme_state(self) -> str:
        """Get current visual theme ('dark' or 'light')."""
        if self._config_manager:
            return self._config_manager.settings.theme
        return "dark"

    def _on_config_changed(self) -> None:
        """Handle config file changes (hot-reload)."""
        if not self._config_manager:
            return

        logger.info("Config change detected, attempting reload...")

        try:
            new_settings = self._config_manager.reload()
        except ConfigurationError as e:
            logger.warning("Config reload failed: %s", e)
            # Previous settings are preserved (transactional reload)
            return

        # Update action router
        if self._action_router:
            self._action_router.update_mappings(new_settings)

        # Update hotkey manager mapped keys
        if self._hotkey_manager and self._action_router:
            self._hotkey_manager.update_mapped_keys(
                self._action_router.mapped_keys
            )

        # Update OSD settings
        if self._osd_service:
            self._osd_service.update_duration(new_settings.osd.duration_ms)
            self._osd_service.update_theme(new_settings.theme)

        logger.info("Configuration reloaded successfully")

    def _on_input_blocked(self) -> None:
        """Handle SendInput being blocked (UIPI)."""
        current = self.state
        if current == AppState.RUNNING:
            self._set_state(AppState.BLOCKED)
            # Schedule a check to see if we're unblocked
            threading.Timer(2.0, self._check_unblocked).start()

    def _check_unblocked(self) -> None:
        """Check if the UIPI block has cleared."""
        if self.state == AppState.BLOCKED:
            # Optimistically return to RUNNING
            self._set_state(AppState.RUNNING)

    def _open_config(self) -> None:
        """Open config.json in the default editor."""
        config_path = get_config_path()
        try:
            os.startfile(str(config_path))
        except Exception:
            logger.exception("Failed to open config file")

    def _run_diagnostic(self) -> None:
        """Run a compatibility diagnostic and print results."""
        try:
            system_info = detect_system()
            report = analyze_compatibility(system_info)
            print(format_report(report))
        except Exception:
            logger.exception("Diagnostic failed")

    def _open_settings(self) -> None:
        """Open the settings window."""
        try:
            SettingsWindow.open(config_path=get_config_path())
        except Exception:
            logger.exception("Failed to open settings window")

    def _open_about(self) -> None:
        """Open the discrete About dialog."""
        try:
            current_theme = self._get_theme_state()
            SettingsWindow.show_about(parent=None, theme_name=current_theme)
        except Exception:
            logger.exception("Failed to open about dialog")

    def _start_console_listener(self) -> None:
        """Start a daemon thread that listens for console commands to exit."""
        def _console_reader() -> None:
            while not self._main_stop.is_set():
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    cmd = line.strip().lower()
                    if cmd in ("q", "quit", "exit"):
                        logger.info("Console exit requested ('%s')", cmd)
                        self.shutdown()
                        break
                except (EOFError, OSError):
                    break
                except Exception:
                    logger.exception("Error in console listener")
                    break

        try:
            if sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
                t = threading.Thread(
                    target=_console_reader,
                    name="ConsoleListener",
                    daemon=True,
                )
                t.start()
        except Exception as e:
            logger.debug("Could not start console listener: %s", e)

    def _request_quit(self) -> None:
        """Handle quit request from tray or signal."""
        self.shutdown()

    def shutdown(self) -> None:
        """Perform a full, ordered, idempotent shutdown.

        1. Close any open settings GUI
        2. Stop event dispatcher
        3. Unhook keyboard and stop hotkey manager
        4. Stop config watcher
        5. Close OSD
        6. Destroy tray icon
        7. Close IPC quit event
        8. Release single-instance mutex
        """
        with self._shutdown_lock:
            if self._is_stopped:
                return
            self._is_stopped = True

        self._set_state(AppState.STOPPING)
        logger.info("Shutting down...")

        # Close any open settings window
        try:
            SettingsWindow.close()
        except Exception:
            pass

        # 1. Stop event dispatcher
        try:
            self._dispatcher_stop.set()
            if self._dispatcher_thread:
                self._dispatcher_thread.join(timeout=2.0)
                self._dispatcher_thread = None
        except Exception:
            logger.exception("Error stopping event dispatcher")

        # 2. Stop hotkey manager (unhooks + stops message pump)
        try:
            if self._hotkey_manager:
                self._hotkey_manager.stop()
                self._hotkey_manager = None
        except Exception:
            logger.exception("Error stopping hotkey manager")

        # 3. Stop config watcher
        try:
            if self._config_watcher:
                self._config_watcher.stop()
                self._config_watcher = None
        except Exception:
            logger.exception("Error stopping config watcher")

        # 4. Stop OSD
        try:
            if self._osd_service:
                self._osd_service.shutdown()
                self._osd_service = None
        except Exception:
            logger.exception("Error stopping OSD service")

        # 5. Stop tray
        try:
            if self._tray_app:
                self._tray_app.shutdown()
                self._tray_app = None
        except Exception:
            logger.exception("Error stopping tray application")

        # 6. Close IPC quit event
        try:
            if self._quit_event:
                close_event(self._quit_event)
                self._quit_event = None
        except Exception:
            pass

        # 7. Release mutex (guaranteed to be reached)
        try:
            if self._mutex_handle:
                release_mutex(self._mutex_handle)
                self._mutex_handle = None
        except Exception:
            logger.exception("Error releasing mutex")

        self._set_state(AppState.STOPPED)
        logger.info("Shutdown complete")

        # Unblock main thread - guaranteed
        self._main_stop.set()

    def _signal_handler(self, signum, frame) -> None:
        """Handle SIGINT/SIGTERM by initiating shutdown."""
        logger.info("Signal %d received, shutting down...", signum)
        self.shutdown()

    def _exception_handler(self, exc_type, exc_value, exc_tb) -> None:
        """Handle uncaught exceptions by initiating shutdown."""
        logger.exception(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        self.shutdown()


def _setup_logging(debug: bool) -> None:
    """Configure logging (stderr only — zero disk logs)."""
    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="WinMediaDeck",
        description=(
            "Remap F1-F12 keys to media controls, system launchers, "
            "and more. Runs as a system tray application."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output to stderr (no disk logs).",
    )
    parser.add_argument(
        "--quit",
        "-q",
        action="store_true",
        help="Cierra completamente cualquier instancia de WinMediaDeck en ejecucion y sale.",
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Run a system compatibility diagnostic and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"WinMediaDeck {__version__}",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    # Ensure Per-Monitor V2 DPI awareness early at startup
    _set_dpi_awareness()

    # Attach to parent console if invoked from terminal (CLI flags)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.AttachConsole(-1)
        except Exception:
            pass

    # Ensure UTF-8 output in Windows console
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = _parse_args()
    _setup_logging(debug=args.debug)

    if args.quit:
        if signal_quit_event():
            print("Señal de cierre enviada a WinMediaDeck.")
            time.sleep(1.0)
            print("WinMediaDeck se ha cerrado completamente.")
            return 0
        else:
            print("WinMediaDeck no está en ejecución.", file=sys.stderr)
            return 1

    if args.diagnostic:
        try:
            system_info = detect_system()
            report = analyze_compatibility(system_info)
            print(format_report(report))
            return 0
        except Exception as e:
            print(f"Diagnostic failed: {e}", file=sys.stderr)
            return 1

    lifecycle = LifecycleManager(debug=args.debug)
    exit_code = lifecycle.run()
    try:
        os._exit(exit_code)
    except Exception:
        return exit_code


if __name__ == "__main__":
    sys.exit(main())
