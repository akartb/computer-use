"""
Integration tests for Computer Use Plugin.

Tests end-to-end flows: plugin discovery, loading, action loop execution,
adapter selection, and full task lifecycle.
"""

import asyncio
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.config import AppConfig, load_config
from src.core.context import ExecutionContext, TaskStatus
from src.core.plugin_manager import PluginManager
from src.core.enhanced_loop import EnhancedActionLoop
from src.core.loop import ActionLoop
from src.sdk.models import Screenshot
from src.sdk.types import ActionType


def _make_screenshot(data: str = "", width: int = 1920, height: int = 1080) -> Screenshot:
    """Create a minimal Screenshot for testing with valid base64 PNG data."""
    if not data:
        import base64
        import io
        from PIL import Image
        img = Image.new("RGB", (64, 64), (128, 128, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = base64.b64encode(buf.getvalue()).decode("utf-8")
    return Screenshot(data=data, width=width, height=height)


def async_test(coro):
    """Helper to run async test functions synchronously."""
    def wrapper(*args, **kwargs):
        return asyncio.run(coro(*args, **kwargs))
    return wrapper


class TestPluginManagerIntegration:
    """Integration tests for PluginManager with real plugin modules."""

    def test_discover_plugins_from_default_dirs(self):
        """Should discover actual plugins from src/plugins/."""
        pm = PluginManager()
        discovered = pm.discover_plugins()
        names = {p.name for p in discovered}
        # Core plugins that must be discoverable (may fail if deps missing)
        assert "screen-mss" in names, f"screen-mss not in {names}"
        assert "safety-guardrail" in names, f"safety-guardrail not in {names}"
        # input-pyautogui may fail to discover if pyautogui not installed
        # recorder is optional (depends on directory scanning)

    def test_discovered_plugins_have_valid_info(self):
        """Discovered plugins should have proper metadata."""
        pm = PluginManager()
        discovered = pm.discover_plugins()
        for plugin_info in discovered:
            assert plugin_info.name, f"Plugin {plugin_info} has no name"
            assert plugin_info.version, f"Plugin {plugin_info.name} has no version"
            assert plugin_info.plugin_class is not None, f"{plugin_info.name} has no class"

    @async_test
    async def test_load_and_unload_screen_plugin(self):
        """Should load and unload the screen capture plugin."""
        pm = PluginManager()
        pm.discover_plugins()

        plugin = await pm.load_plugin("screen-mss")
        assert plugin.initialized
        assert plugin.name == "screen-mss"

        await pm.unload_plugin("screen-mss")
        assert not plugin.initialized
        assert "screen-mss" not in pm._plugins

    @async_test
    async def test_load_all_plugins(self):
        """Should load all discovered plugins without errors."""
        pm = PluginManager()
        pm.discover_plugins()

        loaded = await pm.load_all()
        assert len(loaded) == len(pm._plugin_infos)
        for plugin in loaded:
            assert plugin.initialized

        await pm.teardown_all()
        assert len(pm._plugins) == 0

    @async_test
    async def test_plugin_lifecycle_isolation(self):
        """One plugin crashing should not affect others."""
        pm = PluginManager()
        pm.discover_plugins()

        # Load screen plugin
        screen = await pm.load_plugin("screen-mss")
        assert screen.initialized

        # Loading a non-existent plugin should raise
        with pytest.raises(KeyError, match="not discovered"):
            await pm.load_plugin("nonexistent")

        # Previously loaded plugin should still be fine
        assert screen.initialized
        assert pm.get_plugin("screen-mss") is screen

        await pm.teardown_all()

    def test_list_plugins_shows_status(self):
        """list_plugins should show correct load status."""
        pm = PluginManager()
        pm.discover_plugins()
        info = pm.list_plugins()
        assert "screen-mss" in info
        assert not info["screen-mss"]["loaded"]


class TestActionLoopIntegration:
    """Integration tests for the action loop with mock plugins."""

    def _create_mock_plugins(self, pm: PluginManager):
        """Register mock plugins for testing the action loop."""
        from src.sdk.base import BasePlugin
        from src.sdk.hooks import hookimpl

        class MockScreenPlugin(BasePlugin):
            _capture_count = 0

            @property
            def name(self) -> str:
                return "screen-mss"

            @property
            def version(self) -> str:
                return "mock"

            async def initialize(self, config):
                self._initialized = True

            async def capture(self, monitor=0, region=None):
                self._capture_count += 1
                return _make_screenshot()

            @hookimpl
            def on_capture_screen(self, monitor=0, region=None):
                ss = _make_screenshot()
                return {"data": ss.data, "width": ss.width, "height": ss.height, "monitor": 0, "timestamp": 0.0}

        class MockInputPlugin(BasePlugin):
            _actions: list = []

            @property
            def name(self) -> str:
                return "input-pyautogui"

            @property
            def version(self) -> str:
                return "mock"

            async def initialize(self, config):
                self._initialized = True
                self._actions = []

            @hookimpl
            def on_execute_action(self, action):
                self._actions.append(action)
                return {"success": True, "error": None, "duration_ms": 10.0}

        class MockSafetyPlugin(BasePlugin):
            @property
            def name(self) -> str:
                return "safety-guardrail"

            @property
            def version(self) -> str:
                return "mock"

            async def initialize(self, config):
                self._initialized = True

            @hookimpl
            def on_validate_action(self, action, context):
                return None

            @hookimpl
            def on_action_completed(self, action, result, context):
                pass

            @hookimpl
            def on_task_start(self, task, context):
                pass

            @hookimpl
            def on_task_end(self, task, result, context):
                pass

        class MockAIPlugin(BasePlugin):
            _iteration = 0

            @property
            def name(self) -> str:
                return "ai-openai"

            @property
            def version(self) -> str:
                return "mock"

            async def initialize(self, config):
                self._initialized = True
                self._iteration = 0

            @hookimpl
            def on_reason(self, context, screenshot):
                self._iteration += 1
                if self._iteration >= 5:
                    return {
                        "type": ActionType.DONE,
                        "parameters": {"summary": "Task completed in mock test"},
                        "confidence": 1.0,
                        "reasoning": "Test complete",
                    }
                return {
                    "type": ActionType.CLICK,
                    "parameters": {"x": 100 * self._iteration, "y": 200, "button": "left", "clicks": 1},
                    "confidence": 0.95,
                    "reasoning": f"Click at position {100 * self._iteration}",
                }

            @hookimpl
            def on_task_start(self, task, context):
                self._iteration = 0

        screen = MockScreenPlugin()
        input_ctrl = MockInputPlugin()
        safety = MockSafetyPlugin()
        ai = MockAIPlugin()

        # Set initialized directly since these mocks don't need real async init
        screen._initialized = True
        input_ctrl._initialized = True
        safety._initialized = True
        ai._initialized = True

        for plugin in [screen, input_ctrl, safety, ai]:
            pm._plugins[plugin.name] = plugin
            pm._pm.register(plugin, name=plugin.name)

        return screen, input_ctrl, safety, ai

    @async_test
    async def test_full_action_loop_completion(self):
        """A simple task should complete through the full observe-reason-act cycle."""
        pm = PluginManager()
        screen, input_ctrl, safety, ai = self._create_mock_plugins(pm)

        # Use basic ActionLoop (no visual verification) for integration test
        # since mock screenshots don't reflect realistic UI changes
        loop = ActionLoop(plugin_manager=pm, max_iterations=10)

        result = await loop.run("Click buttons until done")
        assert result["success"] is True
        assert result["total_iterations"] == 5
        assert len(input_ctrl._actions) == 4

        await pm.teardown_all()

    @async_test
    async def test_action_loop_cancellation(self):
        """Cancelling the loop before running should return CANCELLED status."""
        pm = PluginManager()
        screen, input_ctrl, safety, ai = self._create_mock_plugins(pm)

        loop = ActionLoop(plugin_manager=pm, max_iterations=100)
        loop.cancel()

        result = await loop.run("Cancelled task")
        assert result["status"] == TaskStatus.CANCELLED

        await pm.teardown_all()

    @async_test
    async def test_action_loop_pause_resume(self):
        """Pausing and resuming the loop should work correctly."""
        pm = PluginManager()
        screen, input_ctrl, safety, ai = self._create_mock_plugins(pm)

        loop = ActionLoop(plugin_manager=pm, max_iterations=10)

        async def pause_then_resume():
            await asyncio.sleep(0.05)
            loop.pause()
            await asyncio.sleep(0.15)
            loop.resume()

        task_run = asyncio.create_task(loop.run("Task with pause"))
        await pause_then_resume()
        result = await task_run

        assert result["success"] is True

        await pm.teardown_all()

    @async_test
    async def test_action_loop_max_iterations(self):
        """Loop should stop after reaching max iterations."""
        pm = PluginManager()
        screen, input_ctrl, safety, ai = self._create_mock_plugins(pm)

        # The mock AI returns DONE at iteration 5, so max_iterations of 3
        # should cause FAILED status
        loop = ActionLoop(plugin_manager=pm, max_iterations=3)

        result = await loop.run("Short task")
        assert result["success"] is False
        assert result["total_iterations"] == 3

        await pm.teardown_all()


class TestAdapterIntegration:
    """Integration tests for AI adapter selection and initialization."""

    def test_openai_adapter_creation(self):
        """OpenAI adapter should create and initialize correctly."""
        from src.adapters.openai_adapter import OpenAIAdapter
        adapter = OpenAIAdapter()
        assert adapter.name == "ai-openai"
        assert adapter.version == "0.1.0"
        actions = adapter.get_supported_actions()
        assert "click" in actions
        assert "done" in actions

    def test_anthropic_adapter_creation(self):
        """Anthropic adapter should create and initialize correctly."""
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        assert adapter.name == "ai-anthropic"
        assert adapter.version == "0.1.0"
        actions = adapter.get_supported_actions()
        assert len(actions) >= 6

    def test_ollama_adapter_creation(self):
        """Ollama adapter should create with correct defaults."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()
        assert adapter.name == "ai-ollama"
        assert adapter.version == "0.1.0"
        assert adapter._model == "llama3.2-vision"
        assert adapter._base_url == "http://localhost:11434/v1"

    def test_ollama_adapter_supported_actions(self):
        """Ollama adapter should support all action types."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()
        actions = adapter.get_supported_actions()
        for expected in ["click", "type", "key_press", "scroll", "drag", "wait", "screenshot", "done"]:
            assert expected in actions, f"Missing action: {expected}"

    def test_ollama_adapter_parse_valid_json(self):
        """Should parse valid JSON action from model response."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()
        result = adapter._parse_response('{"type": "click", "parameters": {"x": 100, "y": 200}}')
        assert result["type"] == ActionType.CLICK
        assert result["parameters"]["x"] == 100
        assert result["parameters"]["y"] == 200

    def test_ollama_adapter_parse_markdown_fenced_json(self):
        """Should extract JSON from markdown code fences."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()

        response = 'Here is the action:\n```json\n{"type": "type", "parameters": {"text": "hello"}}\n```'
        result = adapter._parse_response(response)
        assert result["type"] == ActionType.TYPE
        assert result["parameters"]["text"] == "hello"

    def test_ollama_adapter_parse_markdown_no_lang(self):
        """Should extract JSON from bare markdown fences."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()

        response = '```\n{"type": "done", "parameters": {"summary": "done"}}\n```'
        result = adapter._parse_response(response)
        assert result["type"] == ActionType.DONE

    def test_ollama_adapter_parse_with_extra_text(self):
        """Should find JSON object within surrounding text."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()

        response = 'I think we should {"type": "scroll", "parameters": {"x": 500, "y": 300, "direction": "down", "amount": 3}} to see more content.'
        result = adapter._parse_response(response)
        assert result["type"] == ActionType.SCROLL

    def test_ollama_adapter_parse_invalid_json_returns_screenshot(self):
        """Should return a SCREENSHOT action when JSON parsing fails."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()

        result = adapter._parse_response("I'm not sure what to do next...")
        assert result["type"] == ActionType.SCREENSHOT
        assert result["confidence"] < 0.5

    def test_ollama_adapter_parse_unknown_action_type(self):
        """Should gracefully handle unknown action types."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()

        result = adapter._parse_response('{"type": "fly", "parameters": {}}')
        assert result["type"] == ActionType.WAIT
        assert result["confidence"] < 0.5

    def test_ollama_adapter_reset_conversation(self):
        """Reset should clear conversation history."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()
        adapter._conversation_history = [{"role": "user", "content": "test"}]
        adapter.reset_conversation()
        assert len(adapter._conversation_history) == 0

    def test_ollama_adapter_build_system_prompt(self):
        """System prompt should contain screen dimensions and task info."""
        from src.adapters.ollama_adapter import OllamaAdapter
        adapter = OllamaAdapter()
        prompt = adapter._build_system_prompt(
            {"task": "Open Notepad"},
            {"width": 1280, "height": 720},
        )
        assert "1280" in prompt
        assert "720" in prompt
        assert "Open Notepad" in prompt
        assert "click" in prompt
        assert "type" in prompt
        assert "done" in prompt


class TestConfigIntegration:
    """Integration tests for configuration loading and validation."""

    def test_load_default_config(self):
        """Loading with no path should use defaults."""
        config = load_config()
        assert config.core.max_iterations == 50
        assert config.safety.enabled is True
        assert config.ai.default_backend == "openai"

    def test_load_custom_config(self):
        """Loading a custom config file should override defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
core:
  max_iterations: 99
  screenshot_format: jpeg
safety:
  mode: sandbox
  blocked_keywords:
    - test
    - secret
ai:
  default_backend: anthropic
""")
            f.flush()
            f.close()
            config = load_config(f.name)
            try:
                os.unlink(f.name)
            except PermissionError:
                pass

        assert config.core.max_iterations == 99
        assert config.core.screenshot_format == "jpeg"
        assert config.safety.mode == "sandbox"
        assert "test" in config.safety.blocked_keywords
        assert config.ai.default_backend == "anthropic"

    def test_config_env_var_substitution(self):
        """Environment variables should be substituted in config values."""
        os.environ["TEST_CU_MAX_ITER"] = "42"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
                f.write("core:\n  max_iterations: ${TEST_CU_MAX_ITER}\n")
                f.flush()
                f.close()
                tmp_path = f.name
                config = load_config(f.name)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except PermissionError:
                    pass
            del os.environ["TEST_CU_MAX_ITER"]

        assert config.core.max_iterations == 42

    def test_save_default_config(self):
        """Saving default config should produce valid YAML."""
        from src.core.config import save_default_config
        tmp_path = os.path.join(tempfile.gettempdir(), f"test_config_{os.getpid()}.yaml")
        try:
            save_default_config(tmp_path)
            assert os.path.getsize(tmp_path) > 100
            reloaded = load_config(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except PermissionError:
                pass

        assert reloaded.core.max_iterations == 50


class TestSafetyIntegration:
    """Integration tests for safety guardrail in the action flow."""

    @async_test
    async def test_guardrail_blocks_low_confidence(self):
        """Actions with confidence below threshold should be rejected."""
        from src.plugins.safety.guardrail import SafetyGuardrailPlugin

        guardrail = SafetyGuardrailPlugin()
        await guardrail.initialize({
            "enabled": True,
            "mode": "auto",
            "confidence_threshold": 0.8,
        })

        # Low confidence action
        result = await guardrail.validate(
            {"type": "click", "parameters": {"x": 100, "y": 100}, "confidence": 0.5},
            {},
        )
        assert result is not None
        assert result["rejected"] is True

        # High confidence action
        result = await guardrail.validate(
            {"type": "click", "parameters": {"x": 100, "y": 100}, "confidence": 0.95},
            {},
        )
        assert result is None

    @async_test
    async def test_guardrail_blocks_negative_coordinates(self):
        """Actions with negative coordinates should be rejected."""
        from src.plugins.safety.guardrail import SafetyGuardrailPlugin

        guardrail = SafetyGuardrailPlugin()
        await guardrail.initialize({
            "enabled": True,
            "mode": "auto",
            "confidence_threshold": 0.7,
        })

        result = await guardrail.validate(
            {"type": "click", "parameters": {"x": -10, "y": 100}, "confidence": 0.9},
            {},
        )
        assert result is not None
        assert result["rejected"] is True

    @async_test
    async def test_guardrail_blocks_keywords_in_type(self):
        """Type actions with blocked keywords should be rejected."""
        from src.plugins.safety.guardrail import SafetyGuardrailPlugin

        guardrail = SafetyGuardrailPlugin()
        await guardrail.initialize({
            "enabled": True,
            "mode": "auto",
            "blocked_keywords": ["delete", "format"],
            "confidence_threshold": 0.5,
        })

        result = await guardrail.validate(
            {"type": "type", "parameters": {"text": "please delete all files"}, "confidence": 0.9},
            {},
        )
        assert result is not None
        assert result["rejected"] is True

    @async_test
    async def test_guardrail_confirm_mode_requires_approval(self):
        """In confirm mode, configured action types should require approval."""
        from src.plugins.safety.guardrail import SafetyGuardrailPlugin

        guardrail = SafetyGuardrailPlugin()
        await guardrail.initialize({
            "enabled": True,
            "mode": "confirm",
            "require_confirmation_for": ["type"],
            "confidence_threshold": 0.5,
        })

        # Type action should require confirmation
        result = await guardrail.validate(
            {"type": "type", "parameters": {"text": "hello"}, "confidence": 0.9},
            {},
        )
        assert result is not None
        assert result["rejected"] is True
        assert "confirmation" in result["reason"].lower()

        # Click action should not require confirmation
        result = await guardrail.validate(
            {"type": "click", "parameters": {"x": 100, "y": 100}, "confidence": 0.9},
            {},
        )
        assert result is None

    @async_test
    async def test_guardrail_disabled_allows_all(self):
        """When disabled, guardrail should allow all actions."""
        from src.plugins.safety.guardrail import SafetyGuardrailPlugin

        guardrail = SafetyGuardrailPlugin()
        await guardrail.initialize({"enabled": False})

        result = await guardrail.validate(
            {"type": "click", "parameters": {"x": -999, "y": -999}, "confidence": 0.1},
            {},
        )
        assert result is None


class TestRecorderIntegration:
    """Integration tests for action recorder in task lifecycle."""

    @async_test
    async def test_record_full_task_lifecycle(self):
        """Should record all events through a complete task lifecycle."""
        from src.plugins.recorder.action_recorder import ActionRecorderPlugin

        recorder = ActionRecorderPlugin()
        await recorder.initialize({"auto_save": False, "save_screenshots": False})

        recorder.on_task_start("Test integration", {"task_id": "int1"})

        for i in range(5):
            recorder.on_action_completed(
                action={"type": "click", "parameters": {"x": i * 50, "y": 100}},
                result={"success": True, "duration_ms": 15.0},
                context={"iteration": i + 1},
            )

        recorder.on_task_end(
            "Test integration",
            {"success": True, "total_iterations": 5, "summary": "Completed"},
            {},
        )

        recording = recorder.get_recording()
        assert recording["task"] == "Test integration"
        assert len(recording["actions"]) == 5
        assert recording["result"]["success"] is True

    @async_test
    async def test_recording_with_failed_actions(self):
        """Should record failed actions with error information."""
        from src.plugins.recorder.action_recorder import ActionRecorderPlugin

        recorder = ActionRecorderPlugin()
        await recorder.initialize({"auto_save": False})

        recorder.on_task_start("Error test", {"task_id": "err1"})

        recorder.on_action_completed(
            action={"type": "click", "parameters": {"x": 0, "y": 0}},
            result={"success": False, "duration_ms": 0, "error": "Click out of bounds"},
            context={"iteration": 1},
        )

        recorder.on_task_end("Error test", {"success": False, "total_iterations": 1}, {})

        recording = recorder.get_recording()
        assert len(recording["actions"]) == 1
        assert recording["actions"][0]["result"]["success"] is False
        assert "Click out of bounds" in recording["actions"][0]["result"]["error"]


class TestEnhancedActionLoopIntegration:
    """Integration tests for the enhanced action loop with verification."""

    @async_test
    async def test_enhanced_loop_includes_retry_count(self):
        """Enhanced loop result should include total_retries field."""
        pm = PluginManager()

        from src.sdk.base import BasePlugin
        from src.sdk.hooks import hookimpl

        class MockScreen(BasePlugin):
            @property
            def name(self) -> str:
                return "screen-mss"

            @property
            def version(self) -> str:
                return "mock"

            async def initialize(self, config):
                self._initialized = True

            async def capture(self, monitor=0, region=None):
                return _make_screenshot()

        class MockInput(BasePlugin):
            @property
            def name(self) -> str:
                return "input-pyautogui"

            @property
            def version(self) -> str:
                return "mock"

            async def initialize(self, config):
                self._initialized = True

            @hookimpl
            def on_execute_action(self, action):
                return {"success": True, "error": None, "duration_ms": 5.0}

        class MockAI(BasePlugin):
            _count = 0

            @property
            def name(self) -> str:
                return "ai-mock"

            @property
            def version(self) -> str:
                return "mock"

            async def initialize(self, config):
                self._initialized = True
                self._count = 0

            @hookimpl
            def on_reason(self, context, screenshot):
                self._count += 1
                if self._count >= 3:
                    return {"type": "done", "parameters": {"summary": "ok"}, "confidence": 1.0}
                return {"type": "click", "parameters": {"x": 100, "y": 100}, "confidence": 0.9}

        screen = MockScreen()
        input_ctrl = MockInput()
        ai = MockAI()

        # Set initialized directly - no real async init needed
        screen._initialized = True
        input_ctrl._initialized = True
        ai._initialized = True

        for p in [screen, input_ctrl, ai]:
            pm._plugins[p.name] = p
            pm._pm.register(p, name=p.name)

        loop = EnhancedActionLoop(plugin_manager=pm, max_iterations=10)
        result = await loop.run("Test enhanced")

        assert result["success"] is True
        assert "total_retries" in result

        await pm.teardown_all()
