"""
OpenAI Computer Use adapter for Computer Use Plugin.

Translates between the unified Action format and OpenAI's computer_use_preview API.
Implements the observe-reason-act loop using the Responses API.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

from src.sdk.base import BasePlugin
from src.sdk.hooks import hookimpl
from src.sdk.types import ActionType, parse_action

logger = logging.getLogger(__name__)


class OpenAIAdapter(BasePlugin):
    """
    AI backend adapter for OpenAI's computer-use-preview model.

    Uses the Responses API with the computer_use_preview tool to analyze
    screenshots and propose actions. Handles the computer_call / 
    computer_call_output protocol defined by OpenAI.

    Configuration:
        model: Model name. Default: 'computer-use-preview'.
        api_key_env: Environment variable name for the API key. Default: 'OPENAI_API_KEY'.
        api_key: Direct API key (overrides api_key_env). Default: None.
        temperature: Model temperature. Default: 0.0.
        max_tokens: Maximum response tokens. Default: 4096.
        base_url: Optional custom API base URL.
    """

    def __init__(self) -> None:
        super().__init__()
        self._client: AsyncOpenAI | None = None
        self._model: str = "computer-use-preview"
        self._temperature: float = 0.0
        self._max_tokens: int = 4096
        self._conversation_history: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "ai-openai"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "OpenAI computer-use-preview model adapter"

    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the OpenAI adapter.

        Args:
            config: Plugin configuration dictionary.
        """
        self._config = config
        self._model = config.get("model", "computer-use-preview")
        self._temperature = config.get("temperature", 0.0)
        self._max_tokens = config.get("max_tokens", 4096)

        api_key = config.get("api_key")
        if not api_key:
            api_key_env = config.get("api_key_env", "OPENAI_API_KEY")
            api_key = os.environ.get(api_key_env)

        base_url = config.get("base_url")

        from openai import AsyncOpenAI

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self._client = AsyncOpenAI(**client_kwargs)
        self._initialized = True
        logger.info("OpenAIAdapter initialized: model=%s", self._model)

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
        Send screenshot to OpenAI CUA model and parse the response into an Action.

        Args:
            context: Execution context dict with 'task', 'history', etc.
            screenshot: Current screenshot dict with 'data', 'width', 'height'.

        Returns:
            Action dict with 'type', 'parameters', 'confidence', 'reasoning'.

        Raises:
            RuntimeError: If the adapter is not initialized or the API call fails.
        """
        if self._client is None:
            raise RuntimeError("OpenAI adapter not initialized")

        if not self._conversation_history:
            self._conversation_history.append({
                "role": "user",
                "content": f"Task: {context.get('task', '')}",
            })

        self._conversation_history.append({
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{screenshot['data']}",
                },
            ],
        })

        try:
            response = await self._client.responses.create(
                model=self._model,
                input=self._conversation_history,
                tools=[{
                    "type": "computer_use_preview",
                    "display_width": screenshot.get("width", 1920),
                    "display_height": screenshot.get("height", 1080),
                }],
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
            )

            for item in response.output:
                if item.type == "computer_call":
                    action = self._parse_computer_call(item)
                    self._conversation_history.append({
                        "role": "assistant",
                        "content": item,
                    })
                    return action

            return {
                "type": ActionType.DONE,
                "parameters": {"summary": "Model did not return a computer call"},
                "confidence": 1.0,
                "reasoning": "No computer_call in response",
            }

        except Exception as e:
            logger.error("OpenAI API call failed: %s", e)
            raise RuntimeError(f"OpenAI API call failed: {e}") from e

    def _parse_computer_call(self, call: Any) -> dict[str, Any]:
        """
        Parse an OpenAI computer_call response into an Action dict.

        Args:
            call: The computer_call object from the API response.

        Returns:
            Action dict with 'type', 'parameters', 'confidence', 'reasoning'.
        """
        action_data = call.action if hasattr(call, "action") else call
        action_type = getattr(action_data, "type", "unknown")

        action_map = {
            "click": ActionType.CLICK,
            "type": ActionType.TYPE,
            "keypress": ActionType.KEY_PRESS,
            "scroll": ActionType.SCROLL,
            "drag": ActionType.DRAG,
            "wait": ActionType.WAIT,
            "screenshot": ActionType.SCREENSHOT,
            "done": ActionType.DONE,
        }

        mapped_type = action_map.get(action_type, ActionType.WAIT)

        parameters: dict[str, Any] = {}
        if mapped_type == ActionType.CLICK:
            parameters = {
                "x": getattr(action_data, "x", 0),
                "y": getattr(action_data, "y", 0),
                "button": getattr(action_data, "button", "left"),
                "clicks": 1,
            }
        elif mapped_type == ActionType.TYPE:
            parameters = {"text": getattr(action_data, "text", "")}
        elif mapped_type == ActionType.KEY_PRESS:
            keys = getattr(action_data, "keys", [])
            if isinstance(keys, str):
                keys = [keys]
            parameters = {"keys": keys}
        elif mapped_type == ActionType.SCROLL:
            parameters = {
                "x": getattr(action_data, "x", 0),
                "y": getattr(action_data, "y", 0),
                "direction": getattr(action_data, "direction", "down"),
                "amount": getattr(action_data, "amount", 3),
            }
        elif mapped_type == ActionType.DRAG:
            parameters = {
                "start_x": getattr(action_data, "start_x", 0),
                "start_y": getattr(action_data, "start_y", 0),
                "end_x": getattr(action_data, "end_x", 0),
                "end_y": getattr(action_data, "end_y", 0),
                "duration": getattr(action_data, "duration", 0.5),
            }
        elif mapped_type == ActionType.WAIT:
            parameters = {"duration": getattr(action_data, "duration", 1.0)}
        elif mapped_type == ActionType.DONE:
            parameters = {"summary": getattr(action_data, "summary", "Task completed")}

        return {
            "type": mapped_type,
            "parameters": parameters,
            "confidence": 0.9,
            "reasoning": f"OpenAI CUA proposed {action_type} action",
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
