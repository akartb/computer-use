"""
Test suite for Phase 2: Smart Wait, Visual Verification, Self-Correction, Enhanced Loop.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.smart_wait import SmartWait
from src.core.visual_verify import VisualVerifier, VerificationResult
from src.core.self_correct import SelfCorrectionEngine, CorrectionStrategy, CorrectionPlan
from src.sdk.types import ActionType
from src.sdk.models import Screenshot


def _make_screenshot(data: str = "dGVzdA==", width: int = 100, height: int = 100) -> Screenshot:
    """Create a minimal Screenshot for testing."""
    return Screenshot(data=data, width=width, height=height)


class TestSmartWait:
    """Tests for the SmartWait system."""

    def test_creation(self):
        sw = SmartWait(stability_threshold=0.01, check_interval=0.05)
        assert sw._stability_threshold == 0.01
        assert sw._check_interval == 0.05

    def test_default_values(self):
        sw = SmartWait()
        assert sw._stability_threshold == 0.005
        assert sw._min_wait == 0.2
        assert sw._max_wait == 10.0

    def test_compute_diff_identical(self):
        """Identical images should have 0 diff ratio."""
        from PIL import Image
        sw = SmartWait()
        img = Image.new("RGB", (100, 100), (128, 128, 128))
        ratio = sw._compute_diff_ratio(img, img)
        assert ratio == 0.0

    def test_compute_diff_different(self):
        """Completely different images should have high diff ratio."""
        from PIL import Image
        sw = SmartWait()
        img1 = Image.new("RGB", (100, 100), (0, 0, 0))
        img2 = Image.new("RGB", (100, 100), (255, 255, 255))
        ratio = sw._compute_diff_ratio(img1, img2)
        assert ratio > 0.9

    def test_compute_diff_slight_change(self):
        """Slight changes should produce low diff ratio."""
        from PIL import Image
        sw = SmartWait()
        img1 = Image.new("RGB", (100, 100), (128, 128, 128))
        img2 = Image.new("RGB", (100, 100), (128, 128, 128))
        img2.putpixel((0, 0), (200, 200, 200))
        ratio = sw._compute_diff_ratio(img1, img2)
        assert 0.0 < ratio < 0.01


class TestVisualVerifier:
    """Tests for the VisualVerifier."""

    def test_should_expect_change_click(self):
        verifier = VisualVerifier()
        assert verifier.should_expect_change({"type": "click"}) is True

    def test_should_expect_change_type(self):
        verifier = VisualVerifier()
        assert verifier.should_expect_change({"type": "type"}) is True

    def test_should_not_expect_change_wait(self):
        verifier = VisualVerifier()
        assert verifier.should_expect_change({"type": "wait"}) is False

    def test_should_not_expect_change_done(self):
        verifier = VisualVerifier()
        assert verifier.should_expect_change({"type": "done"}) is False

    def test_should_not_expect_change_screenshot(self):
        verifier = VisualVerifier()
        assert verifier.should_expect_change({"type": "screenshot"}) is False


class TestSelfCorrectionEngine:
    """Tests for the SelfCorrectionEngine."""

    def test_creation(self):
        engine = SelfCorrectionEngine(max_total_retries=5)
        assert engine._max_total_retries == 5
        assert engine.total_retries == 0

    def test_handle_execution_error_first_retry(self):
        """First execution error should suggest retry."""
        engine = SelfCorrectionEngine()
        plan = engine.analyze_failure(
            action={"type": "click", "parameters": {"x": 100, "y": 200}},
            verification_result=VerificationResult.NO_CHANGE,
            execution_error="Click failed",
        )
        assert plan.strategy == CorrectionStrategy.RETRY
        assert engine.total_retries == 1

    def test_handle_no_change_click(self):
        """Click with no change should suggest retry with adjusted coords."""
        engine = SelfCorrectionEngine()
        plan = engine.analyze_failure(
            action={"type": "click", "parameters": {"x": 100, "y": 200}},
            verification_result=VerificationResult.NO_CHANGE,
        )
        assert plan.strategy == CorrectionStrategy.RETRY
        if plan.action:
            assert plan.action["parameters"]["x"] != 100 or plan.action["parameters"]["y"] != 200

    def test_escalate_after_repeated_failures(self):
        """After many failures, should escalate to AI."""
        engine = SelfCorrectionEngine()
        action = {"type": "click", "parameters": {"x": 100, "y": 200}}
        for _ in range(5):
            engine.analyze_failure(action, VerificationResult.NO_CHANGE)
        plan = engine.analyze_failure(action, VerificationResult.NO_CHANGE)
        assert plan.strategy in (CorrectionStrategy.ESCALATE, CorrectionStrategy.ABORT)

    def test_abort_after_max_retries(self):
        """Should abort after exceeding max total retries."""
        engine = SelfCorrectionEngine(max_total_retries=3)
        action = {"type": "click", "parameters": {"x": 100, "y": 200}}
        for _ in range(3):
            engine.analyze_failure(action, VerificationResult.NO_CHANGE)
        plan = engine.analyze_failure(action, VerificationResult.NO_CHANGE)
        assert plan.strategy == CorrectionStrategy.ABORT

    def test_reset(self):
        """Reset should clear all failure counts."""
        engine = SelfCorrectionEngine()
        engine.analyze_failure(
            {"type": "click", "parameters": {}},
            VerificationResult.NO_CHANGE,
        )
        assert engine.total_retries > 0
        engine.reset()
        assert engine.total_retries == 0
        assert len(engine._failure_counts) == 0

    def test_adjust_click_coordinates(self):
        """Coordinate adjustment should shift by ±5 pixels."""
        engine = SelfCorrectionEngine()
        original = {"type": "click", "parameters": {"x": 100, "y": 200}}
        adjusted = engine._adjust_click_coordinates(original)
        assert adjusted["parameters"]["x"] != 100 or adjusted["parameters"]["y"] != 200
        assert adjusted["parameters"]["x"] >= 0
        assert adjusted["parameters"]["y"] >= 0

    def test_unexpected_change_triggers_reobserve(self):
        """Unexpected change should trigger re-observation."""
        engine = SelfCorrectionEngine()
        plan = engine.analyze_failure(
            {"type": "click", "parameters": {"x": 100, "y": 200}},
            VerificationResult.UNEXPECTED_CHANGE,
        )
        assert plan.strategy == CorrectionStrategy.REOBSERVE


class TestCorrectionPlan:
    """Tests for CorrectionPlan."""

    def test_creation(self):
        plan = CorrectionPlan(
            strategy=CorrectionStrategy.RETRY,
            action={"type": "click", "parameters": {"x": 105, "y": 205}},
            reason="Adjusted coordinates",
            max_retries=2,
        )
        assert plan.strategy == CorrectionStrategy.RETRY
        assert plan.action is not None
        assert plan.reason == "Adjusted coordinates"
        assert plan.max_retries == 2

    def test_default_values(self):
        plan = CorrectionPlan(strategy=CorrectionStrategy.ABORT, reason="Max retries")
        assert plan.action is None
        assert plan.max_retries == 3


class TestAnthropicAdapter:
    """Tests for the Anthropic adapter (unit tests without API calls)."""

    def test_creation(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        assert adapter.name == "ai-anthropic"
        assert adapter.version == "0.1.0"

    def test_supported_actions(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        actions = adapter.get_supported_actions()
        assert "click" in actions
        assert "type" in actions
        assert "key_press" in actions
        assert "scroll" in actions
        assert "done" in actions

    def test_parse_left_click(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        result = adapter._parse_tool_use({
            "action": "left_click",
            "coordinate": [500, 300],
        })
        assert result["type"] == ActionType.CLICK
        assert result["parameters"]["x"] == 500
        assert result["parameters"]["y"] == 300
        assert result["parameters"]["button"] == "left"

    def test_parse_right_click(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        result = adapter._parse_tool_use({
            "action": "right_click",
            "coordinate": [500, 300],
        })
        assert result["type"] == ActionType.CLICK
        assert result["parameters"]["button"] == "right"

    def test_parse_double_click(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        result = adapter._parse_tool_use({
            "action": "double_click",
            "coordinate": [500, 300],
        })
        assert result["type"] == ActionType.CLICK
        assert result["parameters"]["clicks"] == 2

    def test_parse_type(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        result = adapter._parse_tool_use({
            "action": "type",
            "text": "Hello World",
        })
        assert result["type"] == ActionType.TYPE
        assert result["parameters"]["text"] == "Hello World"

    def test_parse_key(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        result = adapter._parse_tool_use({
            "action": "key",
            "key": "ctrl+c",
        })
        assert result["type"] == ActionType.KEY_PRESS
        assert "ctrl" in result["parameters"]["keys"]
        assert "c" in result["parameters"]["keys"]

    def test_parse_scroll(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        result = adapter._parse_tool_use({
            "action": "scroll",
            "coordinate": [500, 300],
            "delta": {"delta_y": -3},
        })
        assert result["type"] == ActionType.SCROLL
        assert result["parameters"]["direction"] == "up"

    def test_parse_drag(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        result = adapter._parse_tool_use({
            "action": "left_click_drag",
            "start_coordinate": [100, 100],
            "coordinate": [200, 200],
        })
        assert result["type"] == ActionType.DRAG
        assert result["parameters"]["start_x"] == 100
        assert result["parameters"]["end_x"] == 200

    def test_reset_conversation(self):
        from src.adapters.anthropic_adapter import AnthropicAdapter
        adapter = AnthropicAdapter()
        adapter._conversation_history = [{"role": "user", "content": "test"}]
        adapter.reset_conversation()
        assert len(adapter._conversation_history) == 0
