"""Win32 registry access for autostart management.

Manages the HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
key to add/remove WinMediaDeck from Windows startup.
"""

import logging
import sys
import winreg
from typing import Optional

logger = logging.getLogger(__name__)

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "WinMediaDeck"


class RegistryError(Exception):
    """Raised when a registry operation fails."""
    pass


def get_autostart_path() -> Optional[str]:
    """Get the current autostart executable path from the registry.

    Returns:
        The path string if autostart is enabled, None otherwise.
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, reg_type = winreg.QueryValueEx(key, _APP_NAME)
            return str(value)
    except FileNotFoundError:
        return None
    except OSError as e:
        logger.warning("Failed to read autostart registry key: %s", e)
        return None


def set_autostart(executable_path: str) -> None:
    """Enable autostart by writing the executable path to the registry.

    Args:
        executable_path: Full path to the WinMediaDeck executable.

    Raises:
        RegistryError: If the registry write fails.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, executable_path)
        logger.info("Autostart enabled: %s", executable_path)
    except OSError as e:
        raise RegistryError(f"Failed to set autostart: {e}") from e


def remove_autostart() -> None:
    """Disable autostart by removing the registry entry.

    Idempotent: does nothing if the entry doesn't exist.

    Raises:
        RegistryError: If the deletion fails for reasons other than
                       the key not existing.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_WRITE
        ) as key:
            winreg.DeleteValue(key, _APP_NAME)
        logger.info("Autostart disabled")
    except FileNotFoundError:
        logger.debug("Autostart entry not found — nothing to remove")
    except OSError as e:
        raise RegistryError(f"Failed to remove autostart: {e}") from e


def is_autostart_enabled() -> bool:
    """Check whether autostart is currently enabled."""
    return get_autostart_path() is not None
