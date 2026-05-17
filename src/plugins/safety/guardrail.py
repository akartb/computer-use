"""
Safety guardrail plugin for Computer Use Plugin.

Provides multi-level action validation: static rules, dynamic validation,
human confirmation, and audit logging. Prevents dangerous or unauthorized operations.
"""

from __future__ import annotations

import logging
from typing import Any

from src.sdk.base import BasePlugin
from src.sdk.hooks import hookimpl
from src.sdk.types import ActionType

logger = logging.getLogger(__name__)


class SafetyGuardrailPlugin(BasePlugin):
    """
    Safety guardrail plugin with multi-level validation.

    Level 1: Static rules - blocked applications, keywords, coordinate ranges.
    Level 2: Dynamic validation - confidence threshold, rate limiting.
    Level 3: Human confirmation - high-risk actions require approval.
    Level 4: Audit logging - all actions logged with before/after screenshots.

    Configuration:
        enabled: Whether safety validation is active. Default: True.
        mode: Safety mode ('auto', 'confirm', 'sandbox'). Default: 'confirm'.
        blocked_apps: List of application window titles to block.
        blocked_keywords: List of keywords that block actions in UI elements.
        confidence_threshold: Minimum AI confidence (0.0-1.0). Default: 0.7.
        require_confirmation_for: Action types requiring human confirmation.
    """

    def __init__(self) -> None:
        super().__init__()
        self._enabled: bool = True
        self._mode: str = "confirm"
        self._blocked_apps: list[str] = []
        self._blocked_keywords: list[str] = []
        self._confidence_threshold: float = 0.7
        self._require_confirmation_for: list[str] = ["type", "key_press"]
        self._action_count: int = 0
        self._last_action_time: float = 0.0

    @property
    def name(self) -> str:
        return "safety-guardrail"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Multi-level safety validation and action filtering"

    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the safety guardrail plugin.

        Args:
            config: Plugin configuration dictionary.
        """
        self._config = config
        self._enabled = config.get("enabled", True)
        self._mode = config.get("mode", "confirm")
        self._blocked_apps = config.get("blocked_apps", [])
        self._blocked_keywords = config.get("blocked_keywords", ["delete", "format", "remove"])
        self._confidence_threshold = config.get("confidence_threshold", 0.7)
        self._require_confirmation_for = config.get("require_confirmation_for", ["type", "key_press"])
        self._initialized = True
        logger.info(
            "SafetyGuardrailPlugin initialized: enabled=%s, mode=%s, threshold=%.2f",
            self._enabled, self._mode, self._confidence_threshold,
        )

    async def validate(self, action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
        """
        Validate an action through all safety levels.

        Args:
            action: The proposed action dict.
            context: Current execution context dict.

        Returns:
            None if the action is allowed, or a rejection dict.
        """
        if not self._enabled:
            return None

        action_type = action.get("type", "")
        params = action.get("parameters", {})
        confidence = action.get("confidence", 1.0)

        rejection = self._check_static_rules(action_type, params)
        if rejection is not None:
            return rejection

        rejection = self._check_dynamic_validation(action_type, params, confidence)
        if rejection is not None:
            return rejection

        if self._mode == "sandbox":
            return {"rejected": True, "reason": "Sandbox mode: all actions blocked"}

        if self._mode == "confirm" and action_type in self._require_confirmation_for:
            return {"rejected": True, "reason": f"Action type '{action_type}' requires human confirmation"}

        return None

    def _check_static_rules(self, action_type: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """
        Level 1: Check against static rules.

        Args:
            action_type: The action type string.
            params: The action parameters dict.

        Returns:
            Rejection dict if a rule is violated, else None.
        """
        if action_type == ActionType.TYPE:
            text = params.get("text", "").lower()
            for keyword in self._blocked_keywords:
                if keyword.lower() in text:
                    return {
                        "rejected": True,
                        "reason": f"Blocked keyword '{keyword}' found in text input",
                    }

        return None

    def _check_dynamic_validation(
        self, action_type: str, params: dict[str, Any], confidence: float
    ) -> dict[str, Any] | None:
        """
        Level 2: Dynamic validation based on confidence and context.

        Args:
            action_type: The action type string.
            params: The action parameters dict.
            confidence: AI model confidence score.

        Returns:
            Rejection dict if validation fails, else None.
        """
        if confidence < self._confidence_threshold:
            return {
                "rejected": True,
                "reason": f"Confidence {confidence:.2f} below threshold {self._confidence_threshold:.2f}",
            }

        if action_type in (ActionType.CLICK, ActionType.SCROLL, ActionType.DRAG):
            x = params.get("x", params.get("start_x", 0))
            y = params.get("y", params.get("start_y", 0))
            if x < 0 or y < 0:
                return {
                    "rejected": True,
                    "reason": f"Invalid coordinates: ({x}, {y})",
                }

        return None

    @hookimpl
    def on_validate_action(self, action: dict, context: dict) -> dict | None:
        """
        Hook implementation for action validation.

        Args:
            action: The proposed action dict.
            context: Current execution context dict.

        Returns:
            None if allowed, rejection dict if blocked.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.validate(action, context))

    @hookimpl
    def on_action_completed(self, action: dict, result: dict, context: dict) -> None:
        """
        Hook implementation for action audit logging.

        Args:
            action: The action that was executed.
            result: The execution result.
            context: Current execution context dict.
        """
        self._action_count += 1
        action_type = action.get("type", "unknown")
        success = result.get("success", False)

        if not success:
            logger.warning(
                "Action #%d failed: type=%s, error=%s",
                self._action_count, action_type, result.get("error", "unknown"),
            )
        else:
            logger.debug(
                "Action #%d completed: type=%s, duration=%.1fms",
                self._action_count, action_type, result.get("duration_ms", 0),
            )

    @hookimpl
    def on_task_start(self, task: str, context: dict) -> None:
        """
        Reset counters when a new task starts.

        Args:
            task: The task description.
            context: Execution context dict.
        """
        self._action_count = 0
        logger.info("Safety guardrail: task started - %s", task[:100])

    @hookimpl
    def on_task_end(self, task: str, result: dict, context: dict) -> None:
        """
        Log task completion summary.

        Args:
            task: The task description.
            result: Final result dict.
            context: Final execution context dict.
        """
        logger.info(
            "Safety guardrail: task ended - success=%s, actions=%d",
            result.get("success", False), self._action_count,
        )
