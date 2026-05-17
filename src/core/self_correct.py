"""
Self-Correction Engine for Computer Use Plugin.

When an action fails or doesn't produce the expected result, this engine
analyzes the failure and proposes corrective actions. This is what makes
the system "more stable than humans" — it automatically recovers from
errors that would stump a human operator.

Correction strategies:
1. Retry: Same action with slight coordinate adjustment
2. Re-observe: Take a fresh screenshot and re-reason
3. Alternative: Try a different approach to achieve the same goal
4. Escalate: Ask the AI model for a recovery plan
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from src.sdk.models import Screenshot
from src.sdk.types import ActionType
from src.core.visual_verify import VerificationResult

logger = logging.getLogger(__name__)


class CorrectionStrategy(str, Enum):
    """Available correction strategies."""

    RETRY = "retry"
    REOBSERVE = "reobserve"
    ALTERNATIVE = "alternative"
    ESCALATE = "escalate"
    ABORT = "abort"


class CorrectionPlan:
    """
    A plan for correcting a failed action.

    Attributes:
        strategy: The correction strategy to use.
        action: The corrected action to try (if applicable).
        reason: Why this correction was chosen.
        max_retries: Maximum number of retry attempts.
    """

    def __init__(
        self,
        strategy: CorrectionStrategy,
        action: dict[str, Any] | None = None,
        reason: str = "",
        max_retries: int = 3,
    ) -> None:
        self.strategy = strategy
        self.action = action
        self.reason = reason
        self.max_retries = max_retries


class SelfCorrectionEngine:
    """
    Engine that analyzes action failures and proposes corrections.

    Tracks failure patterns per task and adapts strategies over time.
    Prevents infinite retry loops by escalating after repeated failures.

    Attributes:
        _failure_counts: Dict mapping action types to failure counts.
        _total_retries: Total number of retries attempted.
        _max_total_retries: Global limit on total retries per task.
    """

    def __init__(self, max_total_retries: int = 10) -> None:
        """
        Initialize the self-correction engine.

        Args:
            max_total_retries: Maximum total retries across all actions per task.
        """
        self._failure_counts: dict[str, int] = {}
        self._total_retries = 0
        self._max_total_retries = max_total_retries

    def analyze_failure(
        self,
        action: dict[str, Any],
        verification_result: VerificationResult,
        execution_error: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> CorrectionPlan:
        """
        Analyze a failed action and propose a correction plan.

        Args:
            action: The action that failed.
            verification_result: Result of visual verification.
            execution_error: Error message from action execution, if any.
            context: Current execution context dict.

        Returns:
            CorrectionPlan with the recommended strategy.
        """
        action_type = action.get("type", "unknown")
        params = action.get("parameters", {})

        self._failure_counts[action_type] = self._failure_counts.get(action_type, 0) + 1
        failure_count = self._failure_counts[action_type]

        if self._total_retries >= self._max_total_retries:
            logger.warning(
                "SelfCorrection: max total retries (%d) reached, aborting",
                self._max_total_retries,
            )
            return CorrectionPlan(
                strategy=CorrectionStrategy.ABORT,
                reason=f"Exceeded maximum total retries ({self._max_total_retries})",
            )

        if execution_error is not None:
            return self._handle_execution_error(action, execution_error, failure_count)

        if verification_result == VerificationResult.NO_CHANGE:
            return self._handle_no_change(action, failure_count)

        if verification_result == VerificationResult.UNEXPECTED_CHANGE:
            return self._handle_unexpected_change(action, failure_count)

        return CorrectionPlan(
            strategy=CorrectionStrategy.REOBSERVE,
            reason="Unknown verification result, re-observing",
        )

    def _handle_execution_error(
        self, action: dict[str, Any], error: str, failure_count: int,
    ) -> CorrectionPlan:
        """
        Handle an action that threw an execution error.

        Args:
            action: The failed action.
            error: The error message.
            failure_count: How many times this action type has failed.

        Returns:
            CorrectionPlan for the execution error.
        """
        action_type = action.get("type", "")

        if failure_count <= 2:
            corrected = self._adjust_action(action)
            self._total_retries += 1
            return CorrectionPlan(
                strategy=CorrectionStrategy.RETRY,
                action=corrected,
                reason=f"Execution error (attempt {failure_count}): {error[:100]}",
                max_retries=2,
            )

        if failure_count <= 4:
            self._total_retries += 1
            return CorrectionPlan(
                strategy=CorrectionStrategy.REOBSERVE,
                reason=f"Repeated execution errors ({failure_count}), re-observing screen",
            )

        self._total_retries += 1
        return CorrectionPlan(
            strategy=CorrectionStrategy.ESCALATE,
            reason=f"Persistent execution errors ({failure_count}), asking AI for recovery",
        )

    def _handle_no_change(
        self, action: dict[str, Any], failure_count: int,
    ) -> CorrectionPlan:
        """
        Handle an action that executed but produced no visible change.

        Args:
            action: The action that had no effect.
            failure_count: How many times this action type has failed.

        Returns:
            CorrectionPlan for the no-change situation.
        """
        action_type = action.get("type", "")

        if action_type == ActionType.CLICK and failure_count <= 2:
            corrected = self._adjust_click_coordinates(action)
            self._total_retries += 1
            return CorrectionPlan(
                strategy=CorrectionStrategy.RETRY,
                action=corrected,
                reason="Click had no effect, adjusting coordinates slightly",
                max_retries=2,
            )

        if failure_count <= 3:
            self._total_retries += 1
            return CorrectionPlan(
                strategy=CorrectionStrategy.REOBSERVE,
                reason=f"Action had no effect (attempt {failure_count}), re-observing",
            )

        self._total_retries += 1
        return CorrectionPlan(
            strategy=CorrectionStrategy.ESCALATE,
            reason=f"Action consistently has no effect ({failure_count} times)",
        )

    def _handle_unexpected_change(
        self, action: dict[str, Any], failure_count: int,
    ) -> CorrectionPlan:
        """
        Handle an action that produced an unexpected visual change.

        Args:
            action: The action that caused unexpected results.
            failure_count: How many times this has happened.

        Returns:
            CorrectionPlan for the unexpected change.
        """
        self._total_retries += 1
        return CorrectionPlan(
            strategy=CorrectionStrategy.REOBSERVE,
            reason="Action produced unexpected change, re-observing to assess state",
        )

    def _adjust_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Make minor adjustments to a failed action for retry.

        Args:
            action: The original action dict.

        Returns:
            Adjusted action dict.
        """
        action_type = action.get("type", "")
        params = dict(action.get("parameters", {}))

        if action_type == ActionType.CLICK:
            params = self._adjust_click_coordinates({"parameters": params})["parameters"]
        elif action_type == ActionType.TYPE:
            pass
        elif action_type == ActionType.KEY_PRESS:
            pass

        return {"type": action_type, "parameters": params}

    def _adjust_click_coordinates(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Slightly adjust click coordinates to handle minor targeting errors.

        Adds a small offset (±5 pixels) to click coordinates, which helps
        when the AI model's coordinate prediction is slightly off — a common
        issue with screenshot-based coordinate estimation.

        Args:
            action: Action dict with click parameters.

        Returns:
            Action dict with adjusted coordinates.
        """
        params = dict(action.get("parameters", {}))
        x = params.get("x", 0)
        y = params.get("y", 0)

        offset = 5
        x = x + (offset if x % 2 == 0 else -offset)
        y = y + (offset if y % 2 == 0 else -offset)

        params["x"] = max(0, x)
        params["y"] = max(0, y)

        return {"type": action.get("type", ActionType.CLICK), "parameters": params}

    def reset(self) -> None:
        """
        Reset failure tracking for a new task.
        """
        self._failure_counts.clear()
        self._total_retries = 0

    @property
    def total_retries(self) -> int:
        """
        Return the total number of retries attempted.

        Returns:
            Integer count of total retries.
        """
        return self._total_retries
