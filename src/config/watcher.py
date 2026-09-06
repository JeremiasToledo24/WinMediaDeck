"""File watcher for config.json using watchdog (ReadDirectoryChangesW).

Push-based change detection with debounce to handle editors that
generate multiple filesystem events per save operation.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent

logger = logging.getLogger(__name__)

# Debounce window: multiple events within this period are collapsed
_DEBOUNCE_SECONDS = 0.2


class _ConfigFileHandler(FileSystemEventHandler):
    """Watchdog handler that fires a debounced callback on config changes."""

    def __init__(
        self,
        config_filename: str,
        on_change: Callable[[], None],
        debounce_seconds: float = _DEBOUNCE_SECONDS,
    ):
        super().__init__()
        self._config_filename = config_filename
        self._on_change = on_change
        self._debounce_seconds = debounce_seconds
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _schedule_callback(self) -> None:
        """Schedule or reschedule the debounced callback."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(
                self._debounce_seconds,
                self._fire_callback,
            )
            self._timer.daemon = True
            self._timer.start()

    def _fire_callback(self) -> None:
        """Execute the change callback."""
        with self._lock:
            self._timer = None
        logger.debug("Config change detected, firing reload callback")
        try:
            self._on_change()
        except Exception:
            logger.exception("Error in config change callback")

    def on_modified(self, event: FileSystemEvent) -> None:
        src = os.fsdecode(event.src_path)
        if not event.is_directory and Path(src).name == self._config_filename:
            self._schedule_callback()

    def on_created(self, event: FileSystemEvent) -> None:
        src = os.fsdecode(event.src_path)
        if not event.is_directory and Path(src).name == self._config_filename:
            self._schedule_callback()

    def on_moved(self, event: FileSystemEvent) -> None:
        # Some editors save via rename (write temp → rename to target)
        dest = getattr(event, "dest_path", None)
        if dest and Path(os.fsdecode(dest)).name == self._config_filename:
            self._schedule_callback()

    def cancel_pending(self) -> None:
        """Cancel any pending debounced callback."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class ConfigWatcher:
    """Watches a config directory for changes and triggers reload.

    Uses watchdog's Observer (which uses ReadDirectoryChangesW on Windows)
    for efficient push-based change detection.
    """

    def __init__(
        self,
        config_dir: Path,
        config_filename: str = "config.json",
        on_change: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            config_dir: The directory to watch.
            config_filename: The specific filename to watch for.
            on_change: Callback invoked when the config file changes
                       (after debounce).
        """
        self._config_dir = config_dir
        self._config_filename = config_filename
        self._on_change = on_change or (lambda: None)
        self._observer: Optional[Any] = None
        self._handler: Optional[_ConfigFileHandler] = None
        self._started = False

    def start(self) -> None:
        """Start watching for config file changes."""
        if self._started:
            return

        self._handler = _ConfigFileHandler(
            config_filename=self._config_filename,
            on_change=self._on_change,
        )

        self._observer = Observer()
        self._observer.schedule(
            self._handler,
            str(self._config_dir),
            recursive=False,
        )
        self._observer.daemon = True
        self._observer.start()
        self._started = True
        logger.info(
            "Config watcher started for %s in %s",
            self._config_filename,
            self._config_dir,
        )

    def stop(self) -> None:
        """Stop watching for changes.

        Idempotent: safe to call multiple times.
        """
        if not self._started:
            return

        if self._handler:
            self._handler.cancel_pending()

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3.0)
            self._observer = None

        self._started = False
        logger.info("Config watcher stopped")

    @property
    def is_running(self) -> bool:
        """True if the watcher is actively monitoring."""
        return self._started
