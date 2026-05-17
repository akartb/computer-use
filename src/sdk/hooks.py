"""
Plugin hook specifications for Computer Use Plugin.

Defines the hook interface that plugins implement to participate in the action loop.
Uses pluggy for hook specification and implementation.
"""

from __future__ import annotations

import pluggy

hookspec = pluggy.HookspecMarker("computer_use")
hookimpl = pluggy.HookimplMarker("computer_use")


class ComputerUseHookSpec:
    """
    Hook specification for the Computer Use Plugin system.

    Plugins implement these hooks to participate in the action loop.
    Each hook corresponds to a phase in the observe-reason-act cycle.
    """

    @hookspec(firstresult=True)
    def on_capture_screen(self, monitor: int = 0, region: dict | None = None) -> dict:
        """
        Capture a screenshot of the current screen state.

        This hook is called during the Observe phase.
        Only the first plugin to implement this hook will be used (firstresult=True).

        Args:
            monitor: Monitor index (0 = primary).
            region: Optional region dict with x, y, width, height.

        Returns:
            Dict with 'data' (base64 PNG), 'width', 'height', 'timestamp'.
        """
        ...

    @hookspec(firstresult=True)
    def on_execute_action(self, action: dict) -> dict:
        """
        Execute an action on the computer.

        This hook is called during the Act phase.
        Only the first plugin to implement this hook will be used (firstresult=True).

        Args:
            action: Action dict with 'type', 'parameters', etc.

        Returns:
            Dict with 'success' (bool), 'error' (str|None), 'duration_ms' (float).
        """
        ...

    @hookspec(firstresult=True)
    def on_reason(self, context: dict, screenshot: dict) -> dict:
        """
        Analyze screenshot and determine the next action.

        This hook is called during the Reason phase.
        Only the first plugin to implement this hook will be used (firstresult=True).

        Args:
            context: Execution context dict with 'task', 'history', etc.
            screenshot: Current screenshot dict.

        Returns:
            Action dict with 'type', 'parameters', 'confidence', 'reasoning'.
        """
        ...

    @hookspec
    def on_validate_action(self, action: dict, context: dict) -> dict | None:
        """
        Validate an action before execution.

        This hook is called before on_execute_action.
        All safety plugins get a chance to validate. If any returns a rejection,
        the action is blocked.

        Args:
            action: The proposed action dict.
            context: Current execution context dict.

        Returns:
            None if the action is allowed, or a dict with 'rejected': True,
            'reason': str if the action should be blocked.
        """
        ...

    @hookspec
    def on_action_completed(self, action: dict, result: dict, context: dict) -> None:
        """
        Called after an action has been executed.

        Used for logging, recording, and auditing. All plugins receive this notification.

        Args:
            action: The action that was executed.
            result: The execution result dict.
            context: Current execution context dict.
        """
        ...

    @hookspec
    def on_task_start(self, task: str, context: dict) -> None:
        """
        Called when a new task begins execution.

        Args:
            task: The natural language task description.
            context: Initial execution context dict.
        """
        ...

    @hookspec
    def on_task_end(self, task: str, result: dict, context: dict) -> None:
        """
        Called when a task completes or fails.

        Args:
            task: The task description.
            result: Final result dict with 'success', 'summary', etc.
            context: Final execution context dict.
        """
        ...
