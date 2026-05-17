"""
Ollama local model adapter for Computer Use Plugin.

Supports running vision-capable models locally through Ollama
for fully offline computer use without cloud API dependencies.
Uses Ollama's OpenAI-compatible API endpoint.
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


class OllamaAdapter(BasePlugin):
    """
    AI backend adapter for locally-running vision models via Ollama.

    Uses Ollama's OpenAI-compatible /v1/chat/completions endpoint.
    Works with vision-capable models such as llama3.2-vision, llava, etc.

    Configuration:
        model: Model name. Default: 'llama3.2-vision'.
        base_url: Ollama server URL. Default: 'http://localhost:11434/v1'.
        api_key: API key (required by OpenAI client, can be 'ollama').
        temperature: Model temperature. Default: 0.0.
        max_tokens: Maximum response tokens. Default: 4096.
    """

    def __init__(self) -> None:
        super().__init__()
        self._client: Any = None
        self._model: str = "llama3.2-vision"
        self._base_url: str = "http://localhost:11434/v1"
        self._temperature: float = 0.0
        self._max_tokens: int = 4096
        self._conversation_history: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "ai-ollama"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Ollama local vision model adapter for offline computer use"

    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the Ollama adapter.

        Args:
            config: Plugin configuration dictionary.
        """
        self._config = config
        self._model = config.get("model", "llama3.2-vision")
        self._temperature = config.get("temperature", 0.0)
        self._max_tokens = config.get("max_tokens", 4096)
        self._base_url = config.get("base_url", "http://localhost:11434/v1")

        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url=self._base_url,
            api_key=config.get("api_key", "ollama"),
        )
        self._initialized = True
        logger.info("OllamaAdapter initialized: model=%s, base_url=%s", self._model, self._base_url)

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
        Send screenshot to local Ollama model and parse the response into an Action.

        Uses a structured system prompt to guide the model to produce
        computer-use actions in the expected JSON format.

        Args:
            context: Execution context dict with 'task', 'history', etc.
            screenshot: Current screenshot dict with 'data', 'width', 'height'.

        Returns:
            Action dict with 'type', 'parameters', 'confidence', 'reasoning'.
        """
        if self._client is None:
            raise RuntimeError("Ollama adapter not initialized")

        system_prompt = self._build_system_prompt(context, screenshot)

        user_content: list[dict[str, Any]] = []

        if not self._conversation_history:
            self._conversation_history.append({
                "role": "system",
                "content": system_prompt,
            })

        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{screenshot['data']}",
            },
        })

        if len(self._conversation_history) <= 1:
            user_content.insert(0, {
                "type": "text",
                "text": f"Current task: {context.get('task', '')}\n\nAnalyze the screenshot and decide the next action.",
            })
        else:
            user_content.insert(0, {
                "type": "text",
                "text": "Here is the updated screenshot. What action should I take next? Reply with JSON only.",
            })

        self._conversation_history.append({
            "role": "user",
            "content": user_content,
        })

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=self._conversation_history,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
            )

            raw_text = response.choices[0].message.content or ""
            logger.debug("Ollama response: %s", raw_text[:300])

            action = self._parse_response(raw_text)

            self._conversation_history.append({
                "role": "assistant",
                "content": raw_text,
            })

            return action

        except Exception as e:
            logger.error("Ollama API call failed: %s", e)
            raise RuntimeError(f"Ollama API call failed: {e}") from e

    def _build_system_prompt(self, context: dict[str, Any], screenshot: dict[str, Any]) -> str:
        """
        Build the system prompt that instructs the model how to output actions.

        Args:
            context: Execution context dict.
            screenshot: Current screenshot dict.

        Returns:
            System prompt string.
        """
        return f"""You are a computer use agent. Your job is to control a computer desktop to accomplish tasks.

The screen is {screenshot.get('width', 1920)}x{screenshot.get('height', 1080)} pixels.

When you see a screenshot, decide the next action and output ONLY a JSON object. No explanation, no markdown.

Available actions and their required parameters:

1. click: Mouse click at coordinates
   {{"type": "click", "parameters": {{"x": <int>, "y": <int>, "button": "left|right|middle", "clicks": 1|2}}}}

2. type: Type text
   {{"type": "type", "parameters": {{"text": "<string>"}}}}

3. key_press: Press key combination
   {{"type": "key_press", "parameters": {{"keys": ["<key1>", "<key2>"]}}}}

4. scroll: Scroll at position
   {{"type": "scroll", "parameters": {{"x": <int>, "y": <int>, "direction": "up|down", "amount": <int>}}}}

5. drag: Drag from one position to another
   {{"type": "drag", "parameters": {{"start_x": <int>, "start_y": <int>, "end_x": <int>, "end_y": <int>, "duration": <float>}}}}

6. wait: Wait for UI changes
   {{"type": "wait", "parameters": {{"duration": <float>}}}}

7. screenshot: Request a fresh screenshot (when you need to re-check the screen state)
   {{"type": "screenshot", "parameters": {{}}}}

8. done: Task is complete
   {{"type": "done", "parameters": {{"summary": "<what was accomplished>"}}}}

Task history from context:
{context.get('task', 'No specific task')}

Coordinates: (0,0) is the top-left corner. X increases right, Y increases down.
Choose the action most likely to advance the task. Output ONLY the JSON."""

    def _parse_response(self, raw_text: str) -> dict[str, Any]:
        """
        Parse the model's text response into an Action dict.

        Handles both raw JSON and markdown-fenced JSON output.

        Args:
            raw_text: The model's raw text response.

        Returns:
            Action dict with 'type', 'parameters', 'confidence', 'reasoning'.
        """
        import json
        import re

        text = raw_text.strip()

        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            text = json_match.group(1).strip()

        fallback_match = re.search(r'\{[\s\S]*"type"[\s\S]*\}', text)
        if fallback_match:
            text = fallback_match.group(0)

        try:
            data = json.loads(text)
            action_type = data.get("type", "")
            valid_types = {t.value for t in ActionType}
            if action_type not in valid_types:
                logger.warning("Ollama returned unknown action type: %s", action_type)
                return {
                    "type": ActionType.WAIT,
                    "parameters": {"duration": 1.0},
                    "confidence": 0.3,
                    "reasoning": f"Ollama model produced unclear action: {raw_text[:200]}",
                }

            return {
                "type": action_type,
                "parameters": data.get("parameters", {}),
                "confidence": 0.7,
                "reasoning": f"Ollama local model proposed action: {raw_text[:200]}",
            }

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse Ollama response as JSON: %s", e)
            return {
                "type": ActionType.SCREENSHOT,
                "parameters": {},
                "confidence": 0.2,
                "reasoning": f"Failed to parse model response: {raw_text[:200]}",
            }

    @hookimpl
    def on_reason(self, context: dict, screenshot: dict) -> dict:
        """
        Hook implementation for AI reasoning via Ollama.

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
