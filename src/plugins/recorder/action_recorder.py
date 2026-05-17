"""
Action Recorder Plugin for Computer Use Plugin.

Records all actions during task execution and supports replay and export.
Saves action history with screenshots as JSON files for audit and replay.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from src.sdk.base import BasePlugin
from src.sdk.hooks import hookimpl
from src.sdk.models import ActionRecord

logger = logging.getLogger(__name__)


class ActionRecorderPlugin(BasePlugin):
    """
    Plugin that records all actions during task execution for replay and audit.

    Records every action with its screenshot context, execution result,
    and timing information. Supports exporting recordings as JSON files
    and replaying them to reproduce the same sequence of actions.

    Configuration:
        save_screenshots: Whether to include base64 screenshots in recordings. Default: True.
        output_dir: Directory path for saved recording files. Default: './recordings'.
        auto_save: Whether to auto-save recording when task ends. Default: True.
    """

    def __init__(self) -> None:
        super().__init__()
        self._save_screenshots: bool = True
        self._output_dir: str = "./recordings"
        self._auto_save: bool = True
        self._current_recording: dict[str, Any] = {}
        self._actions: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "recorder"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Action recording, replay, and export"

    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the action recorder plugin.

        Args:
            config: Plugin configuration dictionary.
        """
        self._config = config
        self._save_screenshots = config.get("save_screenshots", True)
        self._output_dir = config.get("output_dir", "./recordings")
        self._auto_save = config.get("auto_save", True)
        self._initialized = True
        logger.info("ActionRecorderPlugin initialized: output_dir=%s", self._output_dir)

    @hookimpl
    def on_task_start(self, task: str, context: dict) -> None:
        """
        Start a new recording when a task begins.

        Args:
            task: The task description.
            context: Execution context dict.
        """
        self._current_recording = {
            "task": task,
            "task_id": context.get("task_id", ""),
            "start_time": time.time(),
            "actions": [],
        }
        self._actions = []
        logger.info("Recording started for task: %s", task[:80])

    @hookimpl
    def on_action_completed(self, action: dict, result: dict, context: dict) -> None:
        """
        Record an action that was executed.

        Args:
            action: The action that was executed.
            result: The execution result.
            context: Current execution context dict.
        """
        record = {
            "iteration": context.get("iteration", 0),
            "action": action,
            "result": {
                "success": result.get("success", False),
                "duration_ms": result.get("duration_ms", 0),
                "error": result.get("error"),
            },
            "timestamp": time.time(),
        }

        if self._save_screenshots:
            record["screenshot_before"] = action.get("_screenshot_before")
            record["screenshot_after"] = action.get("_screenshot_after")

        self._actions.append(record)

    @hookimpl
    def on_task_end(self, task: str, result: dict, context: dict) -> None:
        """
        Finalize and optionally save the recording when a task ends.

        Args:
            task: The task description.
            result: Final result dict.
            context: Final execution context dict.
        """
        self._current_recording["end_time"] = time.time()
        self._current_recording["duration_ms"] = (
            self._current_recording["end_time"] - self._current_recording["start_time"]
        ) * 1000
        self._current_recording["actions"] = self._actions
        self._current_recording["result"] = {
            "success": result.get("success", False),
            "total_iterations": result.get("total_iterations", 0),
            "summary": result.get("summary", ""),
        }

        if self._auto_save:
            self.save_recording()

        logger.info(
            "Recording finished: %d actions, %.0fms",
            len(self._actions), self._current_recording["duration_ms"],
        )

    def save_recording(self, output_path: str | None = None) -> str:
        """
        Save the current recording to a JSON file.

        Args:
            output_path: Optional custom file path. Auto-generated if None.

        Returns:
            The file path where the recording was saved.
        """
        if not self._current_recording:
            logger.warning("No recording to save")
            return ""

        output_dir = Path(self._output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if output_path is None:
            task_id = self._current_recording.get("task_id", "unknown")
            timestamp = int(self._current_recording.get("start_time", time.time()))
            filename = f"recording_{task_id}_{timestamp}.json"
            output_path = str(output_dir / filename)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self._current_recording, f, indent=2, default=str)

        logger.info("Recording saved to %s", output_path)
        return output_path

    def export_actions(self) -> list[dict[str, Any]]:
        """
        Export the recorded actions as a list of action dicts (for replay).

        Returns:
            List of action dicts suitable for replay.
        """
        return [
            {
                "type": record["action"].get("type"),
                "parameters": record["action"].get("parameters", {}),
            }
            for record in self._actions
            if record["action"].get("type") not in ("done", "screenshot")
        ]

    def get_recording(self) -> dict[str, Any]:
        """
        Get the current recording data.

        Returns:
            The full recording dict.
        """
        return self._current_recording

    @staticmethod
    def load_recording(file_path: str) -> dict[str, Any]:
        """
        Load a recording from a JSON file.

        Args:
            file_path: Path to the recording JSON file.

        Returns:
            The recording dict.
        """
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
