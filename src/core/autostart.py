"""Autostart manager for WinMediaDeck.

Manages the HKCU\\Run registry entry for automatic startup.
Wraps the platform registry module with user-facing operations.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from src.platform.windows.registry import (
    get_autostart_path,
    set_autostart,
    remove_autostart,
    is_autostart_enabled,
    RegistryError,
)

logger = logging.getLogger(__name__)


class AutostartManager:
    """Manages autostart configuration for WinMediaDeck."""

    def __init__(self, executable_path: Optional[str] = None):
        """
        Args:
            executable_path: Path to the executable. Defaults to sys.executable
                             or the PyInstaller bundle path.
        """
        if executable_path:
            self._exe_path = executable_path
        else:
            # Detect if running as PyInstaller bundle
            if getattr(sys, "frozen", False):
                self._exe_path = sys.executable
            else:
                self._exe_path = str(Path(sys.executable).resolve())

    def enable(self) -> bool:
        """Enable autostart.

        Returns:
            True if autostart was successfully enabled.
        """
        try:
            set_autostart(f'"{self._exe_path}"')
            logger.info("Autostart enabled: %s", self._exe_path)
            return True
        except RegistryError as e:
            logger.error("Failed to enable autostart: %s", e)
            return False

    def disable(self) -> bool:
        """Disable autostart.

        Returns:
            True if autostart was successfully disabled.
        """
        try:
            remove_autostart()
            logger.info("Autostart disabled")
            return True
        except RegistryError as e:
            logger.error("Failed to disable autostart: %s", e)
            return False

    def is_enabled(self) -> bool:
        """Check if autostart is currently enabled."""
        return is_autostart_enabled()

    def toggle(self) -> bool:
        """Toggle autostart on/off.

        Returns:
            True if autostart is now enabled, False if disabled.
        """
        if self.is_enabled():
            self.disable()
            return False
        else:
            self.enable()
            return True
