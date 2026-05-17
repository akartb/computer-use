"""
PyAutoGUI-based input control plugin for Computer Use Plugin.

Provides mouse and keyboard simulation using pyautogui and pynput.
Supports click, type, key press, scroll, and drag operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import pyautogui

from src.sdk.base import BasePlugin
from src.sdk.hooks import hookimpl
from src.sdk.types import ActionType

logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


class PyAutoGuiInputPlugin(BasePlugin):
    """
    Input control plugin using pyautogui for mouse and keyboard simulation.

    Supports click, double-click, right-click, text typing, key combinations,
    scrolling, and drag operations with configurable timing and safety.

    Configuration:
        backend: Input backend ('pyautogui' or 'pynput'). Default: 'pyautogui'.
        typing_interval: Delay between keystrokes in seconds. Default: 0.02.
        move_duration: Duration of mouse movement in seconds. Default: 0.3.
        action_delay: Minimum delay between actions in seconds. Default: 0.5.
        fail_safe: Whether to enable fail-safe (move mouse to corner to abort). Default: True.
    """

    def __init__(self) -> None:
        super().__init__()
        self._typing_interval: float = 0.02
        self._move_duration: float = 0.3
        self._action_delay: float = 0.5
        self._fail_safe: bool = True

    @property
    def name(self) -> str:
        return "input-pyautogui"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Mouse and keyboard input simulation using pyautogui"

    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the input control plugin.

        Args:
            config: Plugin configuration dictionary.
        """
        self._config = config
        self._typing_interval = config.get("typing_interval", 0.02)
        self._move_duration = config.get("move_duration", 0.3)
        self._action_delay = config.get("action_delay", 0.5)
        self._fail_safe = config.get("fail_safe", True)
        pyautogui.FAILSAFE = self._fail_safe
        self._initialized = True
        logger.info(
            "PyAutoGuiInputPlugin initialized: typing_interval=%.3f, move_duration=%.3f, fail_safe=%s",
            self._typing_interval, self._move_duration, self._fail_safe,
        )

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        """
        Perform a mouse click at the specified coordinates.

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
            button: Mouse button ('left', 'right', 'middle').
            clicks: Number of clicks (1=single, 2=double, 3=triple).
        """
        pyautogui.moveTo(x, y, duration=self._move_duration)
        await asyncio.sleep(0.05)
        pyautogui.click(x=x, y=y, button=button, clicks=clicks)
        logger.debug("Click: (%d, %d) button=%s clicks=%d", x, y, button, clicks)

    async def type_text(self, text: str, interval: float | None = None) -> None:
        """
        Type text character by character with optional interval.

        Args:
            text: The text string to type.
            interval: Delay between keystrokes in seconds. Uses default if None.
        """
        typing_speed = interval if interval is not None else self._typing_interval
        pyautogui.typewrite(text, interval=typing_speed)
        logger.debug("Type: '%s' (length=%d)", text[:50], len(text))

    async def key_press(self, keys: list[str]) -> None:
        """
        Press a combination of keys (e.g., ['ctrl', 'c']).

        Args:
            keys: List of key names to press simultaneously.
        """
        if len(keys) == 1:
            pyautogui.press(keys[0])
        elif len(keys) > 1:
            pyautogui.hotkey(*keys)
        logger.debug("Key press: %s", "+".join(keys))

    async def scroll(self, x: int, y: int, direction: str = "down", amount: int = 3) -> None:
        """
        Scroll at the specified position.

        Args:
            x: Horizontal pixel coordinate.
            y: Vertical pixel coordinate.
            direction: Scroll direction ('up' or 'down').
            amount: Number of scroll steps.
        """
        pyautogui.moveTo(x, y, duration=self._move_duration)
        await asyncio.sleep(0.05)
        scroll_amount = amount if direction == "down" else -amount
        pyautogui.scroll(scroll_amount, x=x, y=y)
        logger.debug("Scroll: (%d, %d) direction=%s amount=%d", x, y, direction, amount)

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
    ) -> None:
        """
        Drag from one position to another.

        Args:
            start_x: Starting horizontal coordinate.
            start_y: Starting vertical coordinate.
            end_x: Ending horizontal coordinate.
            end_y: Ending vertical coordinate.
            duration: Duration of the drag in seconds.
        """
        pyautogui.moveTo(start_x, start_y, duration=self._move_duration)
        await asyncio.sleep(0.05)
        pyautogui.drag(
            end_x - start_x, end_y - start_y,
            duration=duration,
        )
        logger.debug("Drag: (%d,%d) -> (%d,%d) duration=%.2f", start_x, start_y, end_x, end_y, duration)

    async def execute_action(self, action: dict[str, Any]) -> dict[str, Any]:
        """
        Execute an action based on its type and parameters.

        Args:
            action: Action dict with 'type' and 'parameters'.

        Returns:
            Dict with 'success' (bool), 'error' (str|None), 'duration_ms' (float).
        """
        start_time = time.monotonic()
        action_type = action.get("type", "")
        params = action.get("parameters", {})

        try:
            if action_type == ActionType.CLICK:
                await self.click(
                    x=params.get("x", 0),
                    y=params.get("y", 0),
                    button=params.get("button", "left"),
                    clicks=params.get("clicks", 1),
                )
            elif action_type == ActionType.TYPE:
                await self.type_text(
                    text=params.get("text", ""),
                    interval=params.get("interval"),
                )
            elif action_type == ActionType.KEY_PRESS:
                await self.key_press(keys=params.get("keys", []))
            elif action_type == ActionType.SCROLL:
                await self.scroll(
                    x=params.get("x", 0),
                    y=params.get("y", 0),
                    direction=params.get("direction", "down"),
                    amount=params.get("amount", 3),
                )
            elif action_type == ActionType.DRAG:
                await self.drag(
                    start_x=params.get("start_x", 0),
                    start_y=params.get("start_y", 0),
                    end_x=params.get("end_x", 0),
                    end_y=params.get("end_y", 0),
                    duration=params.get("duration", 0.5),
                )
            elif action_type == ActionType.WAIT:
                duration = params.get("duration", 1.0)
                await asyncio.sleep(duration)
            elif action_type in (ActionType.SCREENSHOT, ActionType.DONE):
                pass
            else:
                return {
                    "success": False,
                    "error": f"Unknown action type: {action_type}",
                    "duration_ms": 0.0,
                }

            elapsed = (time.monotonic() - start_time) * 1000
            if self._action_delay > 0 and action_type not in (ActionType.WAIT, ActionType.DONE):
                remaining = self._action_delay - (elapsed / 1000)
                if remaining > 0:
                    await asyncio.sleep(remaining)

            return {"success": True, "error": None, "duration_ms": elapsed}

        except Exception as e:
            elapsed = (time.monotonic() - start_time) * 1000
            logger.error("Action execution failed: %s - %s", action_type, e)
            return {"success": False, "error": str(e), "duration_ms": elapsed}

    @hookimpl
    def on_execute_action(self, action: dict) -> dict:
        """
        Hook implementation for action execution.

        Args:
            action: Action dict to execute.

        Returns:
            Execution result dict.
        """
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.execute_action(action))
