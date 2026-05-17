"""
Test suite for core SDK types, models, and configuration.
"""

import pytest

from src.sdk.types import (
    ActionType,
    Action,
    ClickAction,
    TypeAction,
    KeyPressAction,
    ScrollAction,
    DragAction,
    WaitAction,
    ScreenshotAction,
    DoneAction,
    parse_action,
)
from src.sdk.models import Region, DisplayInfo, Screenshot, ActionRecord
from src.sdk.base import BasePlugin, PluginInitError
from src.core.config import AppConfig, CoreConfig, SafetyConfig, AIConfig


class TestActionType:
    """Tests for ActionType enum and action parsing."""

    def test_action_type_values(self):
        assert ActionType.CLICK == "click"
        assert ActionType.TYPE == "type"
        assert ActionType.KEY_PRESS == "key_press"
        assert ActionType.SCROLL == "scroll"
        assert ActionType.DRAG == "drag"
        assert ActionType.WAIT == "wait"
        assert ActionType.SCREENSHOT == "screenshot"
        assert ActionType.DONE == "done"

    def test_parse_click_action(self):
        data = {"type": "click", "parameters": {"x": 100, "y": 200}}
        action = parse_action(data)
        assert action.type == ActionType.CLICK
        assert action.parameters["x"] == 100
        assert action.parameters["y"] == 200

    def test_parse_type_action(self):
        data = {"type": "type", "parameters": {"text": "hello world"}}
        action = parse_action(data)
        assert action.type == ActionType.TYPE
        assert action.parameters["text"] == "hello world"

    def test_parse_key_press_action(self):
        data = {"type": "key_press", "parameters": {"keys": ["ctrl", "c"]}}
        action = parse_action(data)
        assert action.type == ActionType.KEY_PRESS
        assert action.parameters["keys"] == ["ctrl", "c"]

    def test_parse_scroll_action(self):
        data = {"type": "scroll", "parameters": {"x": 500, "y": 300, "direction": "up", "amount": 5}}
        action = parse_action(data)
        assert action.type == ActionType.SCROLL
        assert action.parameters["direction"] == "up"

    def test_parse_drag_action(self):
        data = {"type": "drag", "parameters": {"start_x": 0, "start_y": 0, "end_x": 100, "end_y": 100}}
        action = parse_action(data)
        assert action.type == ActionType.DRAG

    def test_parse_wait_action(self):
        data = {"type": "wait", "parameters": {"duration": 2.0}}
        action = parse_action(data)
        assert action.type == ActionType.WAIT
        assert action.parameters["duration"] == 2.0

    def test_parse_done_action(self):
        data = {"type": "done", "parameters": {"summary": "Task completed"}}
        action = parse_action(data)
        assert action.type == ActionType.DONE
        assert action.parameters["summary"] == "Task completed"

    def test_parse_screenshot_action(self):
        data = {"type": "screenshot", "parameters": {}}
        action = parse_action(data)
        assert action.type == ActionType.SCREENSHOT

    def test_parse_action_with_confidence(self):
        data = {"type": "click", "parameters": {"x": 50, "y": 50}, "confidence": 0.85, "reasoning": "test"}
        action = parse_action(data)
        assert action.confidence == 0.85
        assert action.reasoning == "test"

    def test_parse_action_missing_type_raises(self):
        with pytest.raises(ValueError, match="must contain a 'type' field"):
            parse_action({"parameters": {"x": 0}})

    def test_parse_action_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown action type"):
            parse_action({"type": "fly"})


class TestModels:
    """Tests for data models."""

    def test_region_creation(self):
        region = Region(x=10, y=20, width=800, height=600)
        assert region.x == 10
        assert region.width == 800

    def test_display_info_creation(self):
        info = DisplayInfo(index=0, width=1920, height=1080, is_primary=True)
        assert info.is_primary is True
        assert info.dpi_scale == 1.0

    def test_screenshot_creation(self):
        ss = Screenshot(data="base64data", width=1920, height=1080)
        assert ss.data == "base64data"
        assert ss.monitor == 0

    def test_action_record_creation(self):
        record = ActionRecord(iteration=1, action={"type": "click", "parameters": {}})
        assert record.iteration == 1
        assert record.error is None


class TestBasePlugin:
    """Tests for BasePlugin abstract class."""

    def test_cannot_instantiate_base_plugin(self):
        with pytest.raises(TypeError):
            BasePlugin()

    def test_plugin_init_error(self):
        error = PluginInitError("test-plugin", "config missing")
        assert error.plugin_name == "test-plugin"
        assert error.reason == "config missing"
        assert "test-plugin" in str(error)

    def test_concrete_plugin(self):
        class TestPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "test"

            @property
            def version(self) -> str:
                return "1.0.0"

            async def initialize(self, config):
                self._initialized = True

        plugin = TestPlugin()
        assert plugin.name == "test"
        assert plugin.version == "1.0.0"
        assert not plugin.initialized


class TestConfig:
    """Tests for configuration system."""

    def test_default_core_config(self):
        config = CoreConfig()
        assert config.max_iterations == 50
        assert config.action_delay == 0.5
        assert config.screenshot_format == "png"

    def test_default_safety_config(self):
        config = SafetyConfig()
        assert config.enabled is True
        assert config.mode == "confirm"
        assert config.confidence_threshold == 0.7

    def test_default_ai_config(self):
        config = AIConfig()
        assert config.default_backend == "openai"
        assert "openai" in config.backends

    def test_full_app_config_defaults(self):
        config = AppConfig()
        assert config.core.max_iterations == 50
        assert config.safety.mode == "confirm"
        assert config.ai.default_backend == "openai"

    def test_safety_mode_validation(self):
        with pytest.raises(Exception):
            SafetyConfig(mode="invalid")

    def test_screenshot_format_validation(self):
        with pytest.raises(Exception):
            CoreConfig(screenshot_format="bmp")

    def test_confidence_threshold_range(self):
        with pytest.raises(Exception):
            SafetyConfig(confidence_threshold=1.5)


class TestExecutionContext:
    """Tests for ExecutionContext."""

    def test_context_creation(self):
        from src.core.context import ExecutionContext, TaskStatus
        ctx = ExecutionContext(task="Open Chrome")
        assert ctx.task == "Open Chrome"
        assert ctx.status == TaskStatus.PENDING
        assert ctx.iteration == 0
        assert len(ctx.history) == 0

    def test_context_add_action(self):
        from src.core.context import ExecutionContext
        ctx = ExecutionContext(task="test")
        ctx.add_action({"type": "click", "parameters": {"x": 100, "y": 200}})
        assert len(ctx.history) == 1
        assert ctx.history[0].action["type"] == "click"

    def test_context_update_last_action(self):
        from src.core.context import ExecutionContext
        ctx = ExecutionContext(task="test")
        ctx.add_action({"type": "click", "parameters": {}})
        ctx.update_last_action(duration_ms=50.0, error=None)
        assert ctx.history[0].duration_ms == 50.0

    def test_context_to_dict(self):
        from src.core.context import ExecutionContext
        ctx = ExecutionContext(task="test task")
        d = ctx.to_dict()
        assert d["task"] == "test task"
        assert "history" in d

    def test_context_get_result(self):
        from src.core.context import ExecutionContext, TaskStatus
        ctx = ExecutionContext(task="test")
        ctx.status = TaskStatus.COMPLETED
        result = ctx.get_result()
        assert result.success is True
        assert result.status == TaskStatus.COMPLETED
