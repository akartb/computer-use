"""
Anthropic Claude Computer Use adapter for Computer Use Plugin.

Translates between the unified Action format and Anthropic's computer_use tool API.
Implements the observe-reason-act loop using the Messages API.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from src.sdk.base import BasePlugin
from src.sdk.hooks import hookimpl
from src.sdk.types import ActionType

logger = logging.getLogger(__name__)


class AnthropicAdapter(BasePlugin):
    """
    AI backend adapter for Anthropic Claude's computer use tool.

    Uses the Messages API with the computer_20250124 tool type to analyze
    screenshots and propose actions. Handles the tool_use / tool_result
    protocol defined by Anthropic.

    Configuration:
        model: Model name. Default: 'claude-sonnet-4-20250514'.
        api_key_env: Environment variable name for the API key. Default: 'ANTHROPIC_API_KEY'.
        api_key: Direct API key (overrides api_key_env). Default: None.
        temperature: Model temperature. Default: 0.0.
        max_tokens: Maximum response tokens. Default: 4096.
        base_url: Optional custom API base URL.
    """

    def __init__(self) -> None:
        super().__init__()
        self._client: AsyncAnthropic | None = None
        self._model: str = "claude-sonnet-4-20250514"
        self._temperature: float = 0.0
        self._max_tokens: int = 4096
        self._conversation_history: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "ai-anthropic"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Anthropic Claude computer use tool adapter"

    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the Anthropic adapter.

        Args:
            config: Plugin configuration dictionary.
        """
        self._config = config
        self._model = config.get("model", "claude-sonnet-4-20250514")
        self._temperature = config.get("temperature", 0.0)
        self._max_tokens = config.get("max_tokens", 4096)

        api_key = config.get("api_key")
        if not api_key:
            api_key_env = config.get("api_key_env", "ANTHROPIC_API_KEY")
            api_key = os.environ.get(api_key_env)

        base_url = config.get("base_url")

        from anthropic import AsyncAnthropic

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = AsyncAnthropic(**client_kwargs)
        self._initialized = True
        logger.info("AnthropicAdapter initialized: model=%s", self._model)

    def get_supported_actions(self) -> list[str]:
        """
        Return list of action types this adapter can produce.

        Returns:
            List of action type strings.
        """
        return ["click", "type", "key_press", "scroll", "drag", "wait", "screenshot", "done"]

    def reset_conversation(self) -> None:
        """
        Clear the conversation history for a new task.
        """
        self._conversation_history = []

    async def reason(self, context: dict[str, Any], screenshot: dict[str, Any]) -> dict[str, Any]:
        """
        Send screenshot to Anthropic Claude and parse the response into an Action.

        Args:
            context: Execution context dict with 'task', 'history', etc.
            screenshot: Current screenshot dict with 'data', 'width', 'height'.

        Returns:
            Action dict with 'type', 'parameters', 'confidence', 'reasoning'.

        Raises:
            RuntimeError: If the adapter is not initialized or the API call fails.
        """
        if self._client is None:
            raise RuntimeError("Anthropic adapter not initialized")

        if not self._conversation_history:
            self._conversation_history.append({
                "role": "user",
                "content": f"Task: {context.get('task', '')}",
            })

        self._conversation_history.append({
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot["data"],
                    },
                },
            ],
        })

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                tools=[{
                    "type": "computer_20250124",
                    "display_width_px": screenshot.get("width", 1920),
                    "display_height_px": screenshot.get("height", 1080),
                }],
                messages=self._conversation_history,
            )

            for block in response.content:
                if block.type == "tool_use" and block.name == "computer":
                    action = self._parse_tool_use(block.input)
                    self._conversation_history.append({
                        "role": "assistant",
                        "content": [block],
                    })
                    self._conversation_history.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Action executed",
                        }],
                    })
                    return action

            return {
                "type": ActionType.DONE,
                "parameters": {"summary": "Model did not return a tool_use action"},
                "confidence": 1.0,
                "reasoning": "No computer tool_use in response",
            }

        except Exception as e:
            logger.error("Anthropic API call failed: %s", e)
            raise RuntimeError(f"Anthropic API call failed: {e}") from e

    def _parse_tool_use(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """
        Parse an Anthropic tool_use input into an Action dict.

        Args:
            tool_input: The tool_use input dict from the API response.

        Returns:
            Action dict with 'type', 'parameters', 'confidence', 'reasoning'.
        """
        action_type = tool_input.get("action", "unknown")

        action_map = {
            "left_click": ActionType.CLICK,
            "right_click": ActionType.CLICK,
            "middle_click": ActionType.CLICK,
            "double_click": ActionType.CLICK,
            "left_click_drag": ActionType.DRAG,
            "type": ActionType.TYPE,
            "key": ActionType.KEY_PRESS,
            "scroll": ActionType.SCROLL,
            "wait": ActionType.WAIT,
            "screenshot": ActionType.SCREENSHOT,
        }

        mapped_type = action_map.get(action_type, ActionType.WAIT)
        parameters: dict[str, Any] = {}

        if mapped_type == ActionType.CLICK:
            button = "left"
            clicks = 1
            if action_type == "right_click":
                button = "right"
            elif action_type == "middle_click":
                button = "middle"
            elif action_type == "double_click":
                clicks = 2
            parameters = {
                "x": tool_input.get("coordinate", [0, 0])[0],
                "y": tool_input.get("coordinate", [0, 0])[1],
                "button": button,
                "clicks": clicks,
            }
        elif mapped_type == ActionType.TYPE:
            parameters = {"text": tool_input.get("text", "")}
        elif mapped_type == ActionType.KEY_PRESS:
            keys = tool_input.get("key", "")
            if isinstance(keys, str):
                keys = keys.split("+") if "+" in keys else [keys]
            parameters = {"keys": keys}
        elif mapped_type == ActionType.SCROLL:
            scroll_delta = tool_input.get("delta", {})
            direction = "down" if scroll_delta.get("delta_y", 0) > 0 else "up"
            amount = abs(scroll_delta.get("delta_y", 3))
            parameters = {
                "x": tool_input.get("coordinate", [0, 0])[0],
                "y": tool_input.get("coordinate", [0, 0])[1],
                "direction": direction,
                "amount": min(amount, 10),
            }
        elif mapped_type == ActionType.DRAG:
            start = tool_input.get("start_coordinate", [0, 0])
            end = tool_input.get("coordinate", [0, 0])
            parameters = {
                "start_x": start[0],
                "start_y": start[1],
                "end_x": end[0],
                "end_y": end[1],
                "duration": 0.5,
            }
        elif mapped_type == ActionType.WAIT:
            parameters = {"duration": tool_input.get("duration", 2.0)}

        return {
            "type": mapped_type,
            "parameters": parameters,
            "confidence": 0.9,
            "reasoning": f"Anthropic Claude proposed {action_type} action",
        }

    @hookimpl
    def on_reason(self, context: dict, screenshot: dict) -> dict:
        """
        Hook implementation for AI reasoning.

        Args:
            context: Execution context dict.
            screenshot: Current screenshot dict.

        Returns:
            Action dict from the model.
        """
        import asyncio

        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.reason(context, screenshot))

    @hookimpl
    def on_task_start(self, task: str, context: dict) -> None:
        """
        Reset conversation history when a new task starts.

        Args:
            task: The task description.
            context: Execution context dict.
        """
        self.reset_conversation()
