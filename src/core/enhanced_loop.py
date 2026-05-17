"""
Enhanced Action Loop Orchestrator for Computer Use Plugin.

Implements the core Observe → Reason → Act → Verify → Correct loop that
drives task execution. This enhanced version integrates:

1. Smart Wait: Detects UI stability instead of fixed delays
2. Visual Verification: Confirms actions produced expected changes
3. Self-Correction: Automatically recovers from failed actions

This makes the system faster, better, and more stable than human operators:
- Faster: Proceeds immediately when UI is stable (no wasted wait time)
- Better: Verifies every action's effect (catches errors humans miss)
- More Stable: Self-corrects failures (recovers from errors that stump humans)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from src.core.context import ExecutionContext, TaskStatus
from src.core.plugin_manager import PluginManager
from src.core.self_correct import CorrectionStrategy, SelfCorrectionEngine
from src.core.smart_wait import SmartWait
from src.core.visual_verify import VerificationResult, VisualVerifier
from src.sdk.models import Screenshot
from src.sdk.types import ActionType, parse_action

logger = logging.getLogger(__name__)


class EnhancedActionLoop:
    """
    Enhanced Observe → Reason → Act → Verify → Correct orchestrator.

    Integrates smart waiting, visual verification, and self-correction
    into the core action loop for faster, more reliable task execution.

    Attributes:
        _plugin_manager: The plugin manager for accessing loaded plugins.
        _max_iterations: Maximum number of loop iterations.
        _smart_wait: SmartWait instance for intelligent delay.
        _visual_verifier: VisualVerifier for action result checking.
        _correction_engine: SelfCorrectionEngine for failure recovery.
        _on_progress: Optional callback for progress events.
        _on_action_pending: Optional callback for actions requiring confirmation.
        _cancelled: Flag indicating the loop should stop.
        _paused: Flag indicating the loop is paused.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        max_iterations: int = 50,
        smart_wait: SmartWait | None = None,
        visual_verifier: VisualVerifier | None = None,
        correction_engine: SelfCorrectionEngine | None = None,
        on_progress: Callable[[dict], None] | None = None,
        on_action_pending: Callable[[dict], None] | None = None,
    ) -> None:
        """
        Initialize the enhanced action loop.

        Args:
            plugin_manager: Plugin manager with loaded plugins.
            max_iterations: Maximum iterations before forced stop.
            smart_wait: SmartWait instance. Creates default if None.
            visual_verifier: VisualVerifier instance. Creates default if None.
            correction_engine: SelfCorrectionEngine instance. Creates default if None.
            on_progress: Optional callback invoked with progress events.
            on_action_pending: Optional callback for actions needing confirmation.
        """
        self._plugin_manager = plugin_manager
        self._max_iterations = max_iterations
        self._smart_wait = smart_wait or SmartWait()
        self._visual_verifier = visual_verifier or VisualVerifier(self._smart_wait)
        self._correction_engine = correction_engine or SelfCorrectionEngine()
        self._on_progress = on_progress
        self._on_action_pending = on_action_pending
        self._cancelled = False
        self._paused = False

    async def run(self, task: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Execute a task with the enhanced observe-reason-act-verify-correct loop.

        The enhanced loop adds two critical steps after each action:
        1. VERIFY: Check if the action produced the expected visual change
        2. CORRECT: If verification fails, analyze and retry with corrections

        Args:
            task: Natural language description of the task to accomplish.
            config: Optional configuration override for this run.

        Returns:
            TaskResult dictionary with success status, action history, and summary.
        """
        context = ExecutionContext(task=task, config=config)
        context.status = TaskStatus.RUNNING
        self._correction_engine.reset()

        logger.info("Starting enhanced task: %s (max_iterations=%d)", task, self._max_iterations)

        self._plugin_manager.hook.on_task_start(task=task, context=context.to_dict())

        try:
            for i in range(self._max_iterations):
                if self._cancelled:
                    context.status = TaskStatus.CANCELLED
                    logger.info("Task cancelled at iteration %d", i)
                    break

                while self._paused and not self._cancelled:
                    await asyncio.sleep(0.2)

                if self._cancelled:
                    context.status = TaskStatus.CANCELLED
                    break

                context.iteration = i + 1
                logger.debug("Iteration %d/%d", context.iteration, self._max_iterations)

                screenshot = await self._observe(context)
                if screenshot is None:
                    logger.error("Failed to capture screenshot at iteration %d", context.iteration)
                    continue

                action_dict = await self._reason(context, screenshot)
                if action_dict is None:
                    logger.error("AI reasoning failed at iteration %d", context.iteration)
                    continue

                action = parse_action(action_dict)

                if action.type == ActionType.DONE:
                    context.status = TaskStatus.COMPLETED
                    context.add_action(action_dict, screenshot.data)
                    context.update_last_action(duration_ms=0.0)
                    logger.info("Task completed: %s", action.parameters.get("summary", ""))
                    break

                if action.type == ActionType.SCREENSHOT:
                    logger.debug("Model requested re-screenshot")
                    continue

                validation = await self._validate(action_dict, context)
                if validation is not None and validation.get("rejected"):
                    logger.warning(
                        "Action rejected by safety: %s", validation.get("reason", "unknown"),
                    )
                    continue

                context.add_action(action_dict, screenshot.data)

                execution_result = await self._act(action_dict)

                if execution_result.get("success", False):
                    verify_result, after_screenshot = await self._verify(
                        action_dict, screenshot, context,
                    )

                    if verify_result == VerificationResult.NO_CHANGE:
                        correction = self._correction_engine.analyze_failure(
                            action_dict, verify_result,
                            context=context.to_dict(),
                        )
                        handled = await self._handle_correction(
                            correction, context, screenshot,
                        )
                        if not handled:
                            continue
                    else:
                        context.update_last_action(
                            duration_ms=execution_result.get("duration_ms", 0.0),
                        )
                else:
                    error = execution_result.get("error", "Unknown error")
                    correction = self._correction_engine.analyze_failure(
                        action_dict, VerificationResult.NO_CHANGE,
                        execution_error=error,
                        context=context.to_dict(),
                    )
                    context.update_last_action(
                        duration_ms=execution_result.get("duration_ms", 0.0),
                        error=error,
                    )

                    if correction.strategy == CorrectionStrategy.ABORT:
                        context.status = TaskStatus.FAILED
                        logger.error("Aborting task: %s", correction.reason)
                        break

                    handled = await self._handle_correction(
                        correction, context, screenshot,
                    )

                self._plugin_manager.hook.on_action_completed(
                    action=action_dict, result=execution_result, context=context.to_dict(),
                )

                self._emit_progress(context, action_dict, execution_result)

            else:
                context.status = TaskStatus.FAILED
                logger.warning("Task reached max iterations (%d)", self._max_iterations)

        except Exception as e:
            context.status = TaskStatus.FAILED
            logger.error("Task failed with exception: %s", e, exc_info=True)

        task_result = context.get_result()
        task_result_dict = task_result.model_dump()
        task_result_dict["total_retries"] = self._correction_engine.total_retries

        self._plugin_manager.hook.on_task_end(
            task=task, result=task_result_dict, context=context.to_dict(),
        )

        logger.info(
            "Task finished: status=%s, iterations=%d, retries=%d, duration=%.0fms",
            context.status, context.iteration,
            self._correction_engine.total_retries,
            task_result.total_duration_ms,
        )

        return task_result_dict

    async def _observe(self, context: ExecutionContext) -> Screenshot | None:
        """
        Capture a screenshot of the current screen state.

        Args:
            context: Current execution context.

        Returns:
            Screenshot object, or None if capture failed.
        """
        try:
            screen_plugin = self._plugin_manager.get_plugin("screen-mss")
            if screen_plugin is None:
                logger.error("Screen capture plugin not loaded")
                return None

            screenshot = await screen_plugin.capture(
                monitor=context.config.get("screen", {}).get("monitor", 0),
            )
            context.add_screenshot(screenshot)
            return screenshot

        except Exception as e:
            logger.error("Screenshot capture failed: %s", e)
            return None

    async def _reason(self, context: ExecutionContext, screenshot: Screenshot) -> dict[str, Any] | None:
        """
        Send the screenshot and context to the AI model for reasoning.

        Args:
            context: Current execution context.
            screenshot: Current screen capture.

        Returns:
            Action dict from the AI model, or None if reasoning failed.
        """
        try:
            result = self._plugin_manager.hook.on_reason(
                context=context.to_dict(),
                screenshot={
                    "data": screenshot.data,
                    "width": screenshot.width,
                    "height": screenshot.height,
                },
            )
            return result

        except Exception as e:
            logger.error("AI reasoning failed: %s", e)
            return None

    async def _validate(self, action: dict[str, Any], context: ExecutionContext) -> dict[str, Any] | None:
        """
        Validate an action through all safety plugins.

        Args:
            action: The proposed action dict.
            context: Current execution context.

        Returns:
            None if the action is allowed, or a rejection dict.
        """
        results = self._plugin_manager.hook.on_validate_action(
            action=action, context=context.to_dict(),
        )

        if results is None:
            return None

        for result in results:
            if result is not None and result.get("rejected"):
                return result

        return None

    async def _act(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Execute an action through the input control plugin.

        Args:
            action: The validated action dict.

        Returns:
            Execution result dict with 'success', 'error', 'duration_ms'.
        """
        try:
            result = self._plugin_manager.hook.on_execute_action(action=action)
            return result or {"success": False, "error": "No input plugin responded", "duration_ms": 0.0}

        except Exception as e:
            return {"success": False, "error": str(e), "duration_ms": 0.0}

    async def _verify(
        self,
        action: dict[str, Any],
        before_screenshot: Screenshot,
        context: ExecutionContext,
    ) -> tuple[VerificationResult, Screenshot | None]:
        """
        Verify that an action produced the expected visual change.

        Uses SmartWait to wait for UI stability, then checks if
        the screen changed as expected.

        Args:
            action: The action that was executed.
            before_screenshot: Screenshot from before the action.
            context: Current execution context.

        Returns:
            Tuple of (VerificationResult, new Screenshot or None).
        """
        screen_plugin = self._plugin_manager.get_plugin("screen-mss")
        if screen_plugin is None:
            return VerificationResult.MATCH, None

        async def capture():
            return await screen_plugin.capture(
                monitor=context.config.get("screen", {}).get("monitor", 0),
            )

        expect_change = self._visual_verifier.should_expect_change(action)
        return await self._visual_verifier.verify_action(
            action, before_screenshot, capture, expect_change,
        )

    async def _handle_correction(
        self,
        correction: Any,
        context: ExecutionContext,
        before_screenshot: Screenshot,
    ) -> bool:
        """
        Handle a correction plan from the self-correction engine.

        Args:
            correction: CorrectionPlan from the engine.
            context: Current execution context.
            before_screenshot: Screenshot from before the failed action.

        Returns:
            True if the correction was applied successfully, False otherwise.
        """
        from src.core.self_correct import CorrectionPlan

        logger.info(
            "Self-correction: strategy=%s, reason=%s",
            correction.strategy, correction.reason,
        )

        if correction.strategy == CorrectionStrategy.RETRY and correction.action is not None:
            result = await self._act(correction.action)
            if result.get("success", False):
                logger.info("Self-correction retry succeeded")
                return True
            logger.warning("Self-correction retry failed: %s", result.get("error"))
            return False

        if correction.strategy == CorrectionStrategy.REOBSERVE:
            logger.info("Self-correction: re-observing screen")
            return False

        if correction.strategy == CorrectionStrategy.ESCALATE:
            logger.warning("Self-correction: escalating to AI model for recovery")
            return False

        if correction.strategy == CorrectionStrategy.ABORT:
            context.status = TaskStatus.FAILED
            logger.error("Self-correction: aborting task - %s", correction.reason)
            return False

        return False

    def _emit_progress(self, context: ExecutionContext, action: dict, result: dict) -> None:
        """
        Emit a progress event if a callback is registered.

        Args:
            context: Current execution context.
            action: The action that was just executed.
            result: The execution result.
        """
        if self._on_progress is not None:
            self._on_progress({
                "task_id": context.task_id,
                "iteration": context.iteration,
                "action": action,
                "result": result,
                "status": context.status,
                "total_retries": self._correction_engine.total_retries,
            })

    def cancel(self) -> None:
        """
        Cancel the running action loop.
        """
        self._cancelled = True
        logger.info("Enhanced action loop cancellation requested")

    def pause(self) -> None:
        """
        Pause the action loop.
        """
        self._paused = True
        logger.info("Enhanced action loop paused")

    def resume(self) -> None:
        """
        Resume a paused action loop.
        """
        self._paused = False
        logger.info("Enhanced action loop resumed")
