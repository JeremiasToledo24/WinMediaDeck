"""WinMediaDeck — Main entry point.

Orchestrates: CLI parsing, Mutex, Config, State Machine,
Event Dispatcher, Hook, OSD, Tray, and Safe Shutdown.
"""

import argparse
import logging
import os
import queue
import signal
import sys
import threading
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
)
from src.ui.osd import OSDService
from src.ui.tray_app import TrayApp

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

        # 6. Block main thread until shutdown
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
            )

        # Autostart
        self._autostart_manager = AutostartManager()

        # System tray
        self._tray_app = TrayApp(
            on_toggle_pause=self._toggle_pause,
            on_toggle_autostart=self._toggle_autostart,
            on_quit=self._request_quit,
            on_open_config=self._open_config,
            on_diagnostic=self._run_diagnostic,
            get_autostart_state=(
                lambda: self._autostart_manager.is_enabled()
                if self._autostart_manager else False
            ),
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

        1. Disable new event processing
        2. Unhook the keyboard
        3. Clear pressed keys
        4. Stop event dispatcher
        5. Stop config watcher
        6. Close OSD
        7. Destroy tray icon
        8. Release mutex
        """
        with self._shutdown_lock:
            if self._is_stopped:
                return
            self._is_stopped = True

        self._set_state(AppState.STOPPING)
        logger.info("Shutting down...")

        # 1. Stop event dispatcher
        self._dispatcher_stop.set()
        if self._dispatcher_thread:
            self._dispatcher_thread.join(timeout=3.0)
            self._dispatcher_thread = None

        # 2. Stop hotkey manager (unhooks + stops message pump)
        if self._hotkey_manager:
            self._hotkey_manager.stop()
            self._hotkey_manager = None

        # 3. Stop config watcher
        if self._config_watcher:
            self._config_watcher.stop()
            self._config_watcher = None

        # 4. Stop OSD
        if self._osd_service:
            self._osd_service.shutdown()
            self._osd_service = None

        # 5. Stop tray
        if self._tray_app:
            self._tray_app.shutdown()
            self._tray_app = None

        # 6. Release mutex
        if self._mutex_handle:
            release_mutex(self._mutex_handle)
            self._mutex_handle = None

        self._set_state(AppState.STOPPED)
        logger.info("Shutdown complete")

        # Unblock main thread
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
        "--diagnostic",
        action="store_true",
        help="Run a system compatibility diagnostic and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="WinMediaDeck 1.4.0",
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
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
    return lifecycle.run()


if __name__ == "__main__":
    sys.exit(main())
