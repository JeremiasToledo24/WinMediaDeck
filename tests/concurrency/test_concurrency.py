"""Concurrency tests for queue dispatch, shutdown, and reload safety."""

import queue
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from src.core.action_router import ActionRouter
from src.config.settings import (
    ConfigManager,
    ConfigurationError,
    parse_config,
    _default_config_dict,
    write_config_atomic,
)
from src.models.actions import Action
from src.models.events import HotkeyEvent, KeyEventType, HOTKEY_VK_MAP


def _make_event(hotkey: str = "F5") -> HotkeyEvent:
    return HotkeyEvent(
        hotkey_name=hotkey,
        vk_code=HOTKEY_VK_MAP[hotkey],
        event_type=KeyEventType.DOWN,
    )


class TestConcurrentActionRouter:
    """Tests for thread-safe ActionRouter operations."""

    def test_concurrent_resolve_and_update(self):
        """Concurrent resolve and update_mappings don't crash."""
        settings1 = parse_config({
            "schema_version": 1,
            "hotkeys": {"F5": "play_pause"},
        })
        settings2 = parse_config({
            "schema_version": 1,
            "hotkeys": {"F5": "mute"},
        })

        router = ActionRouter(settings1)
        errors = []
        results = []
        stop = threading.Event()

        def resolver():
            while not stop.is_set():
                try:
                    action = router.resolve(_make_event("F5"))
                    if action is not None:
                        results.append(action)
                except Exception as e:
                    errors.append(e)

        def updater():
            for _ in range(100):
                try:
                    router.update_mappings(settings2)
                    router.update_mappings(settings1)
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=resolver),
            threading.Thread(target=resolver),
            threading.Thread(target=updater),
        ]
        for t in threads:
            t.start()

        time.sleep(0.5)
        stop.set()

        for t in threads:
            t.join(timeout=3.0)

        assert len(errors) == 0, f"Errors during concurrent access: {errors}"
        # All resolved actions must be valid
        valid = {Action.PLAY_PAUSE, Action.MUTE}
        for action in results:
            assert action in valid


class TestConcurrentConfigReload:
    """Tests for concurrent config reload safety."""

    def test_concurrent_reloads(self, tmp_path):
        """Multiple concurrent reloads don't corrupt state."""
        config_path = tmp_path / "config.json"
        mgr = ConfigManager(config_path=config_path)
        mgr.load()

        errors = []
        success_count = [0]

        def reload_worker():
            for _ in range(20):
                try:
                    # Alternate between valid configs
                    data = _default_config_dict()
                    data["enabled"] = not data["enabled"]
                    write_config_atomic(data, config_path)
                    mgr.reload()
                    success_count[0] += 1
                except ConfigurationError:
                    pass  # Expected when file is mid-write
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=reload_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        # At least some reloads should have succeeded
        assert success_count[0] > 0


class TestQueueDispatch:
    """Tests for event queue dispatch under load."""

    def test_queue_full_doesnt_block(self):
        """When the queue is full, put_nowait drops the event."""
        q = queue.Queue(maxsize=2)
        q.put_nowait("event1")
        q.put_nowait("event2")

        with pytest.raises(queue.Full):
            q.put_nowait("event3")

        # Queue still functional
        assert q.get_nowait() == "event1"

    def test_high_throughput_dispatch(self):
        """Queue handles high-throughput event dispatch."""
        q = queue.Queue(maxsize=1000)
        processed = []
        stop = threading.Event()

        def producer():
            for i in range(500):
                try:
                    q.put_nowait(f"event_{i}")
                except queue.Full:
                    pass

        def consumer():
            while not stop.is_set() or not q.empty():
                try:
                    event = q.get(timeout=0.1)
                    processed.append(event)
                except queue.Empty:
                    pass

        prod = threading.Thread(target=producer)
        cons = threading.Thread(target=consumer)

        cons.start()
        prod.start()
        prod.join()
        time.sleep(0.3)
        stop.set()
        cons.join(timeout=3.0)

        assert len(processed) > 0
        assert len(processed) <= 500
