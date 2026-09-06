"""Unit tests for configuration management."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.settings import (
    ConfigManager,
    ConfigurationError,
    OSDSettings,
    Settings,
    SCHEMA_VERSION,
    default_settings,
    load_config,
    parse_config,
    write_config_atomic,
    _default_config_dict,
)
from src.models.actions import Action


class TestParseConfig:
    """Tests for parse_config() validation."""

    def test_valid_default_config(self):
        """Default config parses successfully."""
        settings = parse_config(_default_config_dict())
        assert settings.schema_version == 1
        assert settings.enabled is True
        assert settings.osd.enabled is True
        assert settings.osd.duration_ms == 1000
        assert len(settings.hotkeys) == 12

    def test_valid_minimal_config(self):
        """Minimal config with just schema_version and one hotkey."""
        data = {
            "schema_version": 1,
            "hotkeys": {"F5": "play_pause"},
        }
        settings = parse_config(data)
        assert settings.schema_version == 1
        assert settings.enabled is True  # default
        assert len(settings.hotkeys) == 1
        assert settings.hotkeys["F5"] == Action.PLAY_PAUSE

    def test_missing_schema_version(self):
        """Missing schema_version raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Missing 'schema_version'"):
            parse_config({"hotkeys": {}})

    def test_future_schema_version(self):
        """Future schema version is rejected."""
        with pytest.raises(ConfigurationError, match="Unsupported schema version"):
            parse_config({"schema_version": 999})

    def test_past_schema_version(self):
        """Past schema version is rejected if no migration exists."""
        with pytest.raises(ConfigurationError, match="no longer supported"):
            parse_config({"schema_version": 0})

    def test_string_schema_version(self):
        """Non-integer schema_version is rejected."""
        with pytest.raises(ConfigurationError, match="must be an integer"):
            parse_config({"schema_version": "1"})

    def test_invalid_enabled_type(self):
        """Non-boolean enabled is rejected."""
        with pytest.raises(ConfigurationError, match="must be a boolean"):
            parse_config({"schema_version": 1, "enabled": "yes"})

    def test_invalid_osd_type(self):
        """Non-object osd is rejected."""
        with pytest.raises(ConfigurationError, match="must be an object"):
            parse_config({"schema_version": 1, "osd": "enabled"})

    def test_invalid_osd_duration_too_low(self):
        """OSD duration below minimum is rejected."""
        with pytest.raises(ConfigurationError, match="between 100 and 10000"):
            parse_config({
                "schema_version": 1,
                "osd": {"duration_ms": 10},
            })

    def test_invalid_osd_duration_too_high(self):
        """OSD duration above maximum is rejected."""
        with pytest.raises(ConfigurationError, match="between 100 and 10000"):
            parse_config({
                "schema_version": 1,
                "osd": {"duration_ms": 99999},
            })

    def test_invalid_osd_duration_type(self):
        """Non-integer OSD duration is rejected."""
        with pytest.raises(ConfigurationError, match="must be an integer"):
            parse_config({
                "schema_version": 1,
                "osd": {"duration_ms": 1.5},
            })

    def test_boolean_osd_duration_rejected(self):
        """Boolean OSD duration is rejected (isinstance(True, int) is True)."""
        with pytest.raises(ConfigurationError, match="must be an integer"):
            parse_config({
                "schema_version": 1,
                "osd": {"duration_ms": True},
            })

    def test_invalid_hotkey_name(self):
        """Invalid hotkey name (not F1-F12) is rejected."""
        with pytest.raises(ConfigurationError, match="Invalid hotkey 'A'"):
            parse_config({
                "schema_version": 1,
                "hotkeys": {"A": "volume_up"},
            })

    def test_invalid_action_string(self):
        """Unknown action string is rejected."""
        with pytest.raises(ConfigurationError, match="Unknown action"):
            parse_config({
                "schema_version": 1,
                "hotkeys": {"F1": "hack_the_planet"},
            })

    def test_non_string_action(self):
        """Non-string action value is rejected."""
        with pytest.raises(ConfigurationError, match="must be a string"):
            parse_config({
                "schema_version": 1,
                "hotkeys": {"F1": 42},
            })

    def test_empty_hotkeys(self):
        """Empty hotkeys is valid (no keys mapped)."""
        settings = parse_config({"schema_version": 1, "hotkeys": {}})
        assert len(settings.hotkeys) == 0

    def test_disabled_config(self):
        """Config with enabled=false parses correctly."""
        settings = parse_config({
            "schema_version": 1,
            "enabled": False,
        })
        assert settings.enabled is False


class TestAtomicWrite:
    """Tests for write_config_atomic()."""

    def test_write_creates_file(self):
        """Atomic write creates the config file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            data = _default_config_dict()
            write_config_atomic(data, path)

            assert path.exists()
            with open(path, "r") as f:
                loaded = json.load(f)
            assert loaded["schema_version"] == 1

    def test_write_replaces_existing(self):
        """Atomic write replaces existing content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"

            # Write initial
            write_config_atomic({"schema_version": 1, "enabled": True}, path)

            # Overwrite
            write_config_atomic({"schema_version": 1, "enabled": False}, path)

            with open(path, "r") as f:
                loaded = json.load(f)
            assert loaded["enabled"] is False

    def test_write_no_temp_files_left(self):
        """Atomic write doesn't leave temp files behind."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            write_config_atomic(_default_config_dict(), path)

            files = list(Path(tmpdir).iterdir())
            assert len(files) == 1
            assert files[0].name == "config.json"


class TestLoadConfig:
    """Tests for load_config()."""

    def test_load_creates_default(self):
        """load_config creates default if file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            settings = load_config(path)

            assert path.exists()
            assert settings.schema_version == 1
            assert len(settings.hotkeys) == 12

    def test_load_invalid_json(self):
        """load_config rejects invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text("{invalid json", encoding="utf-8")

            with pytest.raises(ConfigurationError, match="not valid JSON"):
                load_config(path)

    def test_load_non_object_root(self):
        """load_config rejects non-object root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")

            with pytest.raises(ConfigurationError, match="must be a JSON object"):
                load_config(path)


class TestConfigManager:
    """Tests for ConfigManager transactional reload."""

    def test_initial_load(self):
        """ConfigManager loads initial config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            mgr = ConfigManager(config_path=path)
            settings = mgr.load()
            assert settings.schema_version == 1

    def test_reload_preserves_on_failure(self):
        """Failed reload preserves previous settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            mgr = ConfigManager(config_path=path)

            # Load valid config
            original = mgr.load()
            assert original.enabled is True

            # Corrupt the file
            path.write_text("{bad json", encoding="utf-8")

            # Reload should fail, preserving original
            with pytest.raises(ConfigurationError):
                mgr.reload()

            # Original settings are still accessible
            assert mgr.settings.enabled is True

    def test_reload_updates_on_success(self):
        """Successful reload swaps settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            mgr = ConfigManager(config_path=path)
            mgr.load()

            # Write new valid config
            new_data = _default_config_dict()
            new_data["enabled"] = False
            write_config_atomic(new_data, path)

            # Reload should succeed
            new_settings = mgr.reload()
            assert new_settings.enabled is False
            assert mgr.settings.enabled is False

    def test_settings_before_load_raises(self):
        """Accessing settings before load raises."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            mgr = ConfigManager(config_path=path)

            with pytest.raises(ConfigurationError, match="not loaded"):
                _ = mgr.settings
