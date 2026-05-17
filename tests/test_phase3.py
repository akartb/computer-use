"""
Test suite for Phase 3: Virtual Cursor, Action Recorder, API Server.
"""

import pytest
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import asyncio

from src.core.virtual_cursor import VirtualCursorOverlay
from src.plugins.recorder.action_recorder import ActionRecorderPlugin
from src.sdk.types import ActionType


def async_test(coro):
    """Helper to run async test functions synchronously."""
    def wrapper(*args, **kwargs):
        return asyncio.run(coro(*args, **kwargs))
    return wrapper


class TestVirtualCursorOverlay:
    """Tests for the VirtualCursorOverlay."""

    def test_creation(self):
        cursor = VirtualCursorOverlay()
        assert cursor._cursor_x == 0
        assert cursor._cursor_y == 0
        assert not cursor._visible

    def test_move_cursor(self):
        cursor = VirtualCursorOverlay()
        cursor.move_cursor(500, 300, "Click here")
        assert cursor._target_x == 500
        assert cursor._target_y == 300
        assert cursor._action_label == "Click here"

    def test_show_click(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.show_click(100, 200, "left", 1)
        assert cursor._root.after.called

    def test_show_type(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.show_type("Hello World")
        assert cursor._root.after.called

    def test_show_scroll(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.show_scroll("down", 3)
        assert cursor._root.after.called

    def test_show_key_press(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.show_key_press(["ctrl", "c"])
        assert cursor._root.after.called

    def test_show_action_click(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.show_action({
            "type": ActionType.CLICK,
            "parameters": {"x": 100, "y": 200, "button": "left", "clicks": 1},
        })
        assert cursor._target_x == 100
        assert cursor._target_y == 200

    def test_show_action_type(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.show_action({
            "type": ActionType.TYPE,
            "parameters": {"text": "test"},
        })
        assert cursor._root.after.called

    def test_show_action_scroll(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.show_action({
            "type": ActionType.SCROLL,
            "parameters": {"x": 500, "y": 300, "direction": "up", "amount": 5},
        })
        assert cursor._target_x == 500

    def test_set_status(self):
        cursor = VirtualCursorOverlay()
        cursor._root = MagicMock()
        cursor.set_status("Running task...")
        assert cursor._status_text == "Running task..."

    def test_stop(self):
        cursor = VirtualCursorOverlay()
        cursor.stop()
        assert not cursor._running


class TestActionRecorderPlugin:
    """Tests for the ActionRecorderPlugin."""

    def test_creation(self):
        recorder = ActionRecorderPlugin()
        assert recorder.name == "recorder"
        assert recorder.version == "0.1.0"

    @async_test
    async def test_initialize(self):
        recorder = ActionRecorderPlugin()
        await recorder.initialize({"output_dir": "/tmp/test_recordings"})
        assert recorder._output_dir == "/tmp/test_recordings"
        assert recorder.initialized

    @async_test
    async def test_task_start_recording(self):
        recorder = ActionRecorderPlugin()
        await recorder.initialize({})
        recorder.on_task_start("Open Chrome", {"task_id": "abc123"})
        assert recorder._current_recording["task"] == "Open Chrome"
        assert recorder._current_recording["task_id"] == "abc123"

    @async_test
    async def test_action_recording(self):
        recorder = ActionRecorderPlugin()
        await recorder.initialize({})
        recorder.on_task_start("Test task", {"task_id": "test1"})
        recorder.on_action_completed(
            action={"type": "click", "parameters": {"x": 100, "y": 200}},
            result={"success": True, "duration_ms": 50.0, "error": None},
            context={"iteration": 1},
        )
        assert len(recorder._actions) == 1
        assert recorder._actions[0]["action"]["type"] == "click"

    @async_test
    async def test_task_end_recording(self):
        recorder = ActionRecorderPlugin()
        await recorder.initialize({"auto_save": False})
        recorder.on_task_start("Test task", {"task_id": "test2"})
        recorder.on_action_completed(
            action={"type": "click", "parameters": {}},
            result={"success": True, "duration_ms": 50.0},
            context={"iteration": 1},
        )
        recorder.on_task_end(
            "Test task",
            {"success": True, "total_iterations": 1},
            {},
        )
        recording = recorder.get_recording()
        assert recording["result"]["success"] is True
        assert len(recording["actions"]) == 1

    @async_test
    async def test_export_actions(self):
        recorder = ActionRecorderPlugin()
        await recorder.initialize({"auto_save": False})
        recorder.on_task_start("Test", {"task_id": "test3"})
        recorder.on_action_completed(
            action={"type": "click", "parameters": {"x": 100, "y": 200}},
            result={"success": True, "duration_ms": 50.0},
            context={"iteration": 1},
        )
        recorder.on_action_completed(
            action={"type": "type", "parameters": {"text": "hello"}},
            result={"success": True, "duration_ms": 30.0},
            context={"iteration": 2},
        )
        recorder.on_action_completed(
            action={"type": "done", "parameters": {"summary": "done"}},
            result={"success": True, "duration_ms": 0.0},
            context={"iteration": 3},
        )
        actions = recorder.export_actions()
        assert len(actions) == 2
        assert actions[0]["type"] == "click"
        assert actions[1]["type"] == "type"

    @async_test
    async def test_save_and_load_recording(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = ActionRecorderPlugin()
            await recorder.initialize({
                "output_dir": tmpdir,
                "auto_save": False,
                "save_screenshots": False,
            })
            recorder.on_task_start("Save test", {"task_id": "save1"})
            recorder.on_action_completed(
                action={"type": "click", "parameters": {"x": 50, "y": 50}},
                result={"success": True, "duration_ms": 20.0},
                context={"iteration": 1},
            )
            recorder.on_task_end("Save test", {"success": True}, {})

            path = recorder.save_recording()
            assert os.path.exists(path)

            loaded = ActionRecorderPlugin.load_recording(path)
            assert loaded["task"] == "Save test"
            assert len(loaded["actions"]) == 1
            assert loaded["actions"][0]["action"]["type"] == "click"

    @async_test
    async def test_multiple_actions_recording(self):
        recorder = ActionRecorderPlugin()
        await recorder.initialize({"auto_save": False})
        recorder.on_task_start("Multi test", {"task_id": "multi1"})

        for i in range(5):
            recorder.on_action_completed(
                action={"type": "click", "parameters": {"x": i * 100, "y": i * 50}},
                result={"success": True, "duration_ms": 10.0 * i},
                context={"iteration": i + 1},
            )

        recorder.on_task_end("Multi test", {"success": True}, {})
        assert len(recorder._actions) == 5
        actions = recorder.export_actions()
        assert len(actions) == 5


class TestAPIServer:
    """Tests for the API server module."""

    def test_server_creation(self):
        from src.api.server import ComputerUseServer
        from src.core.config import AppConfig

        config = AppConfig()
        server = ComputerUseServer(config)
        assert server._config is not None
        assert server._tasks == {}

    def test_server_has_virtual_cursor(self):
        from src.api.server import ComputerUseServer
        from src.core.config import AppConfig

        server = ComputerUseServer(AppConfig())
        assert server._virtual_cursor is not None

    def test_create_action_loop(self):
        from src.api.server import ComputerUseServer
        from src.core.config import AppConfig

        server = ComputerUseServer(AppConfig())
        server._plugin_manager = MagicMock()
        loop = server._create_action_loop()
        assert loop is not None
