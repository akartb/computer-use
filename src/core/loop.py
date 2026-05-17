"""
Action Loop Orchestrator for Computer Use Plugin.

Implements the core Observe → Reason → Act loop that drives task execution.
Coordinates screen capture, AI reasoning, safety validation, and action execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from src.core.context import ExecutionContext, TaskStatus
from src.core.plugin_manager import PluginManager
from src.sdk.models import Screenshot
from src.sdk.types import ActionType, parse_action

logger = logging.getLogger(__name__)


class ActionLoop:
    """
    Orchestrates the Observe → Reason → Act cycle.

    Manages screenshot capture, AI inference, safety validation, and action
    execution in a continuous loop until the task is complete or a limit is reached.

    Attributes:
        _plugin_manager: The plugin manager for accessing loaded plugins.
        _max_iterations: Maximum number of loop iterations.
        _on_progress: Optional callback for progress events.
        _on_action_pending: Optional callback for actions requiring confirmation.
        _cancelled: Flag indicating the loop should stop.
        _paused: Flag indicating the loop is paused.
    """

    def __init__(
        self,
        plugin_manager: PluginManager,
        max_iterations: int = 50,
        on_progress: Callable[[dict], None] | None = None,
        on_action_pending: Callable[[dict], None] | None = None,
    ) -> None:
        """
        Initialize the action loop.

        Args:
            plugin_manager: Plugin manager with loaded plugins.
            max_iterations: Maximum iterations before forced stop.
            on_progress: Optional callback invoked with progress events.
            on_action_pending: Optional callback for actions needing confirmation.
        """
        self._plugin_manager = plugin_manager
        self._max_iterations = max_iterations
        self._on_progress = on_progress
        self._on_action_pending = on_action_pending
        self._cancelled = False
        self._paused = False

    async def run(self, task: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Execute a task by running the action loop.

        The loop follows: Observe (screenshot) → Reason (AI) → Validate (safety)
        → Act (execute) → repeat until done or max iterations reached.

        Args:
            task: Natural language description of the task to accomplish.
            config: Optional configuration override for this run.

        Returns:
            TaskResult dictionary with success status, action history, and summary.
        """
        context = ExecutionContext(task=task, config=config)
        context.status = TaskStatus.RUNNING

        logger.info("Starting task: %s (max_iterations=%d)", task, self._max_iterations)

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

                result = await self._act(action_dict)

                context.update_last_action(
                    duration_ms=result.get("duration_ms", 0.0),
                    error=result.get("error"),
                )

                self._plugin_manager.hook.on_action_completed(
                    action=action_dict, result=result, context=context.to_dict(),
                )

                self._emit_progress(context, action_dict, result)

            else:
                context.status = TaskStatus.FAILED
                logger.warning("Task reached max iterations (%d)", self._max_iterations)

        except Exception as e:
            context.status = TaskStatus.FAILED
            logger.error("Task failed with exception: %s", e, exc_info=True)

        task_result = context.get_result()
        self._plugin_manager.hook.on_task_end(
            task=task, result=task_result.model_dump(), context=context.to_dict(),
        )

        logger.info(
            "Task finished: status=%s, iterations=%d, duration=%.0fms",
            context.status, context.iteration, task_result.total_duration_ms,
        )

        return task_result.model_dump()

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
            None if the action is allowed, or a rejection dict with 'rejected': True.
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
            })

    def cancel(self) -> None:
        """
        Cancel the running action loop.

        The loop will stop at the next iteration check.
        """
        self._cancelled = True
        logger.info("Action loop cancellation requested")

    def pause(self) -> None:
        """
        Pause the action loop.

        The loop will wait at the next iteration until resumed.
        """
        self._paused = True
        logger.info("Action loop paused")

    def resume(self) -> None:
        """
        Resume a paused action loop.
        """
        self._paused = False
        logger.info("Action loop resumed")
