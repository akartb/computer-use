"""
Visual Verification System for Computer Use Plugin.

After each action, verifies that the expected visual change occurred.
If the action didn't produce the expected effect, triggers self-correction.

This is what makes the system "better than humans" — humans often don't
verify their actions worked, leading to cascading errors. This system
checks every action and corrects failures immediately.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from src.sdk.models import Screenshot
from src.core.smart_wait import SmartWait

logger = logging.getLogger(__name__)


class VerificationResult(str, Enum):
    """Result of a visual verification check."""

    MATCH = "match"
    NO_CHANGE = "no_change"
    UNEXPECTED_CHANGE = "unexpected_change"
    TIMEOUT = "timeout"


class VisualVerifier:
    """
    Verifies that actions produced the expected visual changes.

    After each action, captures a new screenshot and compares it with the
    pre-action screenshot. Uses the SmartWait system to wait for changes
    if needed, and classifies the result.

    Attributes:
        _smart_wait: SmartWait instance for change detection.
        _change_timeout: Max seconds to wait for a change after an action.
    """

    def __init__(
        self,
        smart_wait: SmartWait | None = None,
        change_timeout: float = 5.0,
    ) -> None:
        """
        Initialize the visual verifier.

        Args:
            smart_wait: SmartWait instance. Creates default if None.
            change_timeout: Max seconds to wait for a change after an action.
        """
        self._smart_wait = smart_wait or SmartWait()
        self._change_timeout = change_timeout

    async def verify_action(
        self,
        action: dict[str, Any],
        before_screenshot: Screenshot,
        capture_func: Any,
        expect_change: bool = True,
    ) -> tuple[VerificationResult, Screenshot | None]:
        """
        Verify that an action produced the expected visual change.

        Args:
            action: The action that was executed.
            before_screenshot: Screenshot from before the action.
            capture_func: Async callable that returns a new Screenshot.
            expect_change: Whether the action is expected to change the screen.

        Returns:
            Tuple of (VerificationResult, new Screenshot or None).
        """
        action_type = action.get("type", "")

        no_change_types = {"wait", "screenshot"}
        if action_type in no_change_types:
            return VerificationResult.MATCH, None

        if not expect_change:
            after = await self._smart_wait.wait_for_stability(capture_func, before_screenshot)
            return VerificationResult.MATCH, after

        changed_screenshot = await self._smart_wait.wait_for_change(
            capture_func, before_screenshot, timeout=self._change_timeout,
        )

        if changed_screenshot is not None:
            logger.debug(
                "VisualVerify: action '%s' produced expected change",
                action_type,
            )
            return VerificationResult.MATCH, changed_screenshot

        logger.warning(
            "VisualVerify: action '%s' produced NO visible change",
            action_type,
        )
        return VerificationResult.NO_CHANGE, None

    def should_expect_change(self, action: dict[str, Any]) -> bool:
        """
        Determine whether an action type should produce a visible change.

        Args:
            action: The action dict.

        Returns:
            True if the action should change the screen.
        """
        action_type = action.get("type", "")
        no_change_types = {"wait", "screenshot", "done"}
        return action_type not in no_change_types
