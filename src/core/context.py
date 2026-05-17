"""
Execution context management for Computer Use Plugin.

Maintains state across action loop iterations, including conversation history,
screenshots, actions taken, and metadata.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from src.sdk.models import ActionRecord, Screenshot


class TaskStatus(str):
    """Task execution status constants."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskResult(BaseModel):
    """
    Result of a task execution.

    Attributes:
        task_id: Unique task identifier.
        success: Whether the task completed successfully.
        status: Final task status.
        summary: Summary of what was accomplished.
        history: List of action records from the execution.
        total_iterations: Number of loop iterations executed.
        total_duration_ms: Total execution time in milliseconds.
        error: Error message if the task failed.
    """

    task_id: str = ""
    success: bool = False
    status: str = TaskStatus.PENDING
    summary: str = ""
    history: list[ActionRecord] = Field(default_factory=list)
    total_iterations: int = 0
    total_duration_ms: float = 0.0
    error: str | None = None


class ExecutionContext:
    """
    Maintains state across action loop iterations.

    Includes the task description, conversation history for the AI model,
    captured screenshots, executed actions, and arbitrary metadata.
    This context is passed through the entire action loop pipeline.

    Attributes:
        task: Natural language description of the task to accomplish.
        task_id: Unique identifier for this task execution.
        status: Current execution status.
        history: List of action records from all iterations.
        screenshots: List of screenshots captured during execution.
        metadata: Arbitrary metadata dictionary.
        iteration: Current loop iteration number.
        start_time: Unix timestamp when execution started.
        config: Reference to the global configuration.
    """

    def __init__(self, task: str, task_id: str = "", config: dict[str, Any] | None = None) -> None:
        """
        Initialize a new execution context.

        Args:
            task: Natural language task description.
            task_id: Optional unique task identifier. Auto-generated if empty.
            config: Optional global configuration dictionary.
        """
        import uuid

        self.task: str = task
        self.task_id: str = task_id or str(uuid.uuid4())[:8]
        self.status: str = TaskStatus.PENDING
        self.history: list[ActionRecord] = []
        self.screenshots: list[Screenshot] = []
        self.metadata: dict[str, Any] = {}
        self.iteration: int = 0
        self.start_time: float = time.time()
        self.config: dict[str, Any] = config or {}

    def add_action(self, action: dict[str, Any], screenshot_before: str | None = None) -> None:
        """
        Record an action that is about to be executed.

        Args:
            action: The action dict being executed.
            screenshot_before: Base64 screenshot before the action.
        """
        record = ActionRecord(
            iteration=self.iteration,
            action=action,
            screenshot_before=screenshot_before,
            timestamp=time.time(),
        )
        self.history.append(record)

    def update_last_action(
        self,
        screenshot_after: str | None = None,
        duration_ms: float = 0.0,
        error: str | None = None,
    ) -> None:
        """
        Update the most recent action record with execution results.

        Args:
            screenshot_after: Base64 screenshot after the action.
            duration_ms: How long the action took in milliseconds.
            error: Error message if the action failed.
        """
        if self.history:
            last = self.history[-1]
            last.screenshot_after = screenshot_after
            last.duration_ms = duration_ms
            last.error = error

    def add_screenshot(self, screenshot: Screenshot) -> None:
        """
        Add a captured screenshot to the context.

        Args:
            screenshot: The captured Screenshot object.
        """
        self.screenshots.append(screenshot)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the context to a dictionary for AI model consumption.

        Returns:
            Dictionary with task, history, and metadata.
        """
        return {
            "task": self.task,
            "task_id": self.task_id,
            "status": self.status,
            "iteration": self.iteration,
            "history": [
                {
                    "iteration": r.iteration,
                    "action": r.action,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                }
                for r in self.history
            ],
            "metadata": self.metadata,
        }

    def get_result(self) -> TaskResult:
        """
        Build a TaskResult from the current context state.

        Returns:
            TaskResult with all execution data.
        """
        total_duration = (time.time() - self.start_time) * 1000
        summary = ""
        if self.history:
            last_action = self.history[-1].action
            if last_action.get("type") == "done":
                summary = last_action.get("parameters", {}).get("summary", "")

        return TaskResult(
            task_id=self.task_id,
            success=self.status == TaskStatus.COMPLETED,
            status=self.status,
            summary=summary,
            history=self.history,
            total_iterations=self.iteration,
            total_duration_ms=total_duration,
        )
