"""Configuration management for WinMediaDeck.

Handles Schema v1 validation, %LOCALAPPDATA% path resolution,
atomic config file writing, and transactional reload (swap-on-success).

Security: All input from config.json is validated against the Action enum
and schema rules. Invalid configs are rejected — never silently corrected.
"""

import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.models.actions import Action
from src.models.events import HOTKEY_VK_MAP

logger = logging.getLogger(__name__)

# Current schema version
SCHEMA_VERSION = 1

# Valid hotkey names (F1-F12)
VALID_HOTKEYS = frozenset(HOTKEY_VK_MAP.keys())

# App data directory name
APP_DIR_NAME = "WinMediaDeck"


class ConfigurationError(Exception):
    """Raised when config.json is invalid or cannot be loaded."""
    pass


@dataclass(frozen=True, slots=True)
class OSDSettings:
    """OSD display settings.

    Attributes:
        enabled: Whether OSD notifications are shown.
        duration_ms: How long the OSD is displayed (milliseconds).
    """
    enabled: bool = True
    duration_ms: int = 1000


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable, validated application settings (Schema v1).

    Attributes:
        schema_version: The schema version of this configuration.
        enabled: If True, the app starts in RUNNING; if False, PAUSED.
        theme: Application visual theme ('dark' or 'light').
        osd: OSD display settings.
        hotkeys: Mapping of F-key names to Action enum members.
    """
    schema_version: int = SCHEMA_VERSION
    enabled: bool = True
    theme: str = "dark"
    osd: OSDSettings = field(default_factory=OSDSettings)
    hotkeys: dict[str, Action] = field(default_factory=dict)


def get_config_dir() -> Path:
    """Return the configuration directory path.

    Uses %LOCALAPPDATA%\\WinMediaDeck\\.
    Creates the directory if it does not exist.
    """
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        raise ConfigurationError(
            "Environment variable LOCALAPPDATA is not set"
        )
    config_dir = Path(local_app_data) / APP_DIR_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """Return the full path to config.json."""
    return get_config_dir() / "config.json"


def _default_config_dict() -> dict:
    """Return the default config as a dictionary (Schema v1)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": True,
        "theme": "dark",
        "osd": {
            "enabled": True,
            "duration_ms": 1000,
        },
        "hotkeys": {
            "F1": "volume_down",
            "F2": "volume_up",
            "F3": "mute",
            "F4": "previous",
            "F5": "play_pause",
            "F6": "next",
            "F7": "stop",
            "F8": "calculator",
            "F9": "browser",
            "F10": "media_select",
            "F11": "mail",
            "F12": "toggle_pause",
        },
    }


def default_settings() -> Settings:
    """Return the default Settings object."""
    return parse_config(_default_config_dict())


def write_config_atomic(config_dict: dict, config_path: Optional[Path] = None) -> None:
    """Write config to disk atomically (temp file + os.replace).

    Args:
        config_dict: The configuration dictionary to write.
        config_path: Path to the config file. Defaults to get_config_path().

    Raises:
        ConfigurationError: If the write fails.
    """
    if config_path is None:
        config_path = get_config_path()

    config_dir = config_path.parent
    config_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Write to a temp file in the same directory (same volume for atomic rename)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_dir),
            prefix="config_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            # Clean up the temp file on write failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        # Atomic rename (NTFS guarantees atomicity for os.replace)
        os.replace(tmp_path, str(config_path))
        logger.debug("Config written atomically to %s", config_path)

    except Exception as e:
        raise ConfigurationError(f"Failed to write config: {e}") from e


def parse_config(data: dict) -> Settings:
    """Parse and validate a config dictionary against Schema v1.

    Args:
        data: The raw config dictionary (from JSON).

    Returns:
        A validated, immutable Settings object.

    Raises:
        ConfigurationError: If validation fails for any reason.
    """
    # --- Schema version ---
    version = data.get("schema_version")
    if version is None:
        raise ConfigurationError("Missing 'schema_version' field")
    if not isinstance(version, int):
        raise ConfigurationError(
            f"'schema_version' must be an integer, got {type(version).__name__}"
        )
    if version > SCHEMA_VERSION:
        raise ConfigurationError(
            f"Unsupported schema version {version} (max supported: {SCHEMA_VERSION}). "
            "Please update WinMediaDeck."
        )
    if version < SCHEMA_VERSION:
        raise ConfigurationError(
            f"Schema version {version} is no longer supported. "
            "No migration is defined for this version."
        )

    # --- enabled ---
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ConfigurationError(
            f"'enabled' must be a boolean, got {type(enabled).__name__}"
        )

    # --- OSD ---
    osd_data = data.get("osd", {})
    if not isinstance(osd_data, dict):
        raise ConfigurationError(
            f"'osd' must be an object, got {type(osd_data).__name__}"
        )
    osd_enabled = osd_data.get("enabled", True)
    if not isinstance(osd_enabled, bool):
        raise ConfigurationError(
            f"'osd.enabled' must be a boolean, got {type(osd_enabled).__name__}"
        )
    osd_duration = osd_data.get("duration_ms", 1000)
    if not isinstance(osd_duration, int) or isinstance(osd_duration, bool):
        raise ConfigurationError(
            f"'osd.duration_ms' must be an integer, got {type(osd_duration).__name__}"
        )
    if osd_duration < 100 or osd_duration > 10000:
        raise ConfigurationError(
            f"'osd.duration_ms' must be between 100 and 10000, got {osd_duration}"
        )

    # --- Hotkeys ---
    hotkeys_data = data.get("hotkeys", {})
    if not isinstance(hotkeys_data, dict):
        raise ConfigurationError(
            f"'hotkeys' must be an object, got {type(hotkeys_data).__name__}"
        )

    hotkeys: dict[str, Action] = {}
    for key_name, action_str in hotkeys_data.items():
        # Validate key name
        if key_name not in VALID_HOTKEYS:
            raise ConfigurationError(
                f"Invalid hotkey '{key_name}'. "
                f"Valid hotkeys: {', '.join(sorted(VALID_HOTKEYS))}"
            )
        # Validate action (closed enum)
        if not isinstance(action_str, str):
            raise ConfigurationError(
                f"Action for '{key_name}' must be a string, "
                f"got {type(action_str).__name__}"
            )
        try:
            action = Action.from_string(action_str)
        except ValueError as e:
            raise ConfigurationError(str(e)) from e

        hotkeys[key_name] = action

    # --- theme ---
    theme = data.get("theme", "dark")
    if not isinstance(theme, str):
        raise ConfigurationError(
            f"'theme' must be a string, got {type(theme).__name__}"
        )
    if theme.lower() not in ("dark", "light"):
        raise ConfigurationError(
            f"Invalid theme '{theme}'. Must be either 'dark' or 'light'"
        )
    theme = theme.lower()

    return Settings(
        schema_version=version,
        enabled=enabled,
        theme=theme,
        osd=OSDSettings(enabled=osd_enabled, duration_ms=osd_duration),
        hotkeys=hotkeys,
    )


def load_config(config_path: Optional[Path] = None) -> Settings:
    """Load and validate config.json from disk.

    If the file doesn't exist, creates it with default values.

    Args:
        config_path: Path to the config file. Defaults to get_config_path().

    Returns:
        A validated Settings object.

    Raises:
        ConfigurationError: If the file exists but is invalid.
    """
    if config_path is None:
        config_path = get_config_path()

    if not config_path.exists():
        logger.info("Config file not found, creating default at %s", config_path)
        default_dict = _default_config_dict()
        write_config_atomic(default_dict, config_path)
        return parse_config(default_dict)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigurationError(
            f"Config file is not valid JSON: {e}"
        ) from e
    except OSError as e:
        raise ConfigurationError(
            f"Cannot read config file: {e}"
        ) from e

    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Config root must be a JSON object, got {type(data).__name__}"
        )

    return parse_config(data)


class ConfigManager:
    """Thread-safe configuration manager with atomic reload support.

    Holds the current Settings and allows transactional reloads:
    if a reload fails validation, the previous settings are preserved.
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or get_config_path()
        self._lock = threading.Lock()
        self._settings: Optional[Settings] = None

    @property
    def settings(self) -> Settings:
        """Return the current settings (thread-safe read)."""
        with self._lock:
            if self._settings is None:
                raise ConfigurationError("Settings not loaded yet")
            return self._settings

    def load(self) -> Settings:
        """Load settings from disk (initial load or explicit reload).

        Returns:
            The loaded Settings object.

        Raises:
            ConfigurationError: If the config is invalid.
        """
        settings = load_config(self._config_path)
        with self._lock:
            self._settings = settings
        logger.info("Configuration loaded successfully")
        return settings

    def reload(self) -> Settings:
        """Attempt to reload settings from disk.

        On success, atomically swaps the in-memory settings.
        On failure, preserves the previous settings and re-raises.

        Returns:
            The new Settings on success.

        Raises:
            ConfigurationError: If the new config is invalid
                                (previous settings are preserved).
        """
        try:
            new_settings = load_config(self._config_path)
        except ConfigurationError:
            logger.warning(
                "Config reload failed — preserving previous settings"
            )
            raise

        with self._lock:
            self._settings = new_settings
        logger.info("Configuration reloaded successfully")
        return new_settings

    @property
    def config_path(self) -> Path:
        """Return the path to the config file."""
        return self._config_path
