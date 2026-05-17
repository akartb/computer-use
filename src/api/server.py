"""
REST API and WebSocket server for Computer Use Plugin.

Provides HTTP endpoints for task management and plugin control,
plus real-time WebSocket streaming of action progress.

Uses FastAPI for the REST API and WebSocket support.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from src.core.config import AppConfig, load_config
from src.core.enhanced_loop import EnhancedActionLoop
from src.core.plugin_manager import PluginManager
from src.core.self_correct import SelfCorrectionEngine
from src.core.smart_wait import SmartWait
from src.core.visual_verify import VisualVerifier
from src.core.virtual_cursor import VirtualCursorOverlay

logger = logging.getLogger(__name__)


class ComputerUseServer:
    """
    FastAPI server providing REST and WebSocket APIs for Computer Use Plugin.

    REST endpoints for task CRUD, plugin management, and configuration.
    WebSocket for real-time action progress streaming and virtual cursor control.

    Attributes:
        _config: Application configuration.
        _app: FastAPI application instance.
        _plugin_manager: Plugin manager instance.
        _tasks: Dict of running/completed tasks.
        _virtual_cursor: Virtual cursor overlay instance.
        _active_websockets: Set of active WebSocket connections.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        """
        Initialize the server.

        Args:
            config: Application configuration. Loads default if None.
        """
        self._config = config or load_config()
        self._app: Any = None
        self._plugin_manager: PluginManager | None = None
        self._tasks: dict[str, dict[str, Any]] = {}
        self._virtual_cursor = VirtualCursorOverlay()
        self._active_websockets: set[Any] = set()

    def create_app(self) -> Any:
        """
        Create and configure the FastAPI application.

        Returns:
            Configured FastAPI application instance.
        """
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel

        app = FastAPI(
            title="Computer Use Plugin API",
            version="0.1.0",
            description="AI agent for computer GUI interaction",
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        class TaskRequest(BaseModel):
            task: str
            backend: str | None = None
            safety_mode: str | None = None
            max_iterations: int | None = None
            show_cursor: bool = True

        class TaskResponse(BaseModel):
            task_id: str
            status: str
            message: str

        @app.on_event("startup")
        async def startup() -> None:
            await self._initialize_plugins()

        @app.on_event("shutdown")
        async def shutdown() -> None:
            self._virtual_cursor.stop()
            if self._plugin_manager:
                await self._plugin_manager.teardown_all()

        @app.post("/api/v1/tasks", response_model=TaskResponse)
        async def create_task(request: TaskRequest) -> TaskResponse:
            task_id = str(uuid.uuid4())[:8]
            self._tasks[task_id] = {
                "task": request.task,
                "status": "pending",
                "backend": request.backend,
                "safety_mode": request.safety_mode,
                "max_iterations": request.max_iterations,
                "show_cursor": request.show_cursor,
            }

            asyncio.create_task(self._run_task(task_id, request))

            return TaskResponse(
                task_id=task_id,
                status="pending",
                message=f"Task '{request.task[:50]}' queued",
            )

        @app.get("/api/v1/tasks/{task_id}")
        async def get_task(task_id: str) -> dict[str, Any]:
            if task_id not in self._tasks:
                return {"error": f"Task '{task_id}' not found"}
            return self._tasks[task_id]

        @app.post("/api/v1/tasks/{task_id}/cancel")
        async def cancel_task(task_id: str) -> dict[str, str]:
            if task_id not in self._tasks:
                return {"error": f"Task '{task_id}' not found"}
            self._tasks[task_id]["status"] = "cancelled"
            return {"status": "cancelled", "task_id": task_id}

        @app.get("/api/v1/tasks")
        async def list_tasks() -> dict[str, Any]:
            return {"tasks": self._tasks}

        @app.get("/api/v1/plugins")
        async def list_plugins() -> dict[str, Any]:
            if self._plugin_manager is None:
                return {"plugins": {}}
            return {"plugins": self._plugin_manager.list_plugins()}

        @app.get("/api/v1/screenshot")
        async def capture_screenshot() -> dict[str, Any]:
            screen_plugin = self._plugin_manager.get_plugin("screen-mss") if self._plugin_manager else None
            if screen_plugin is None:
                return {"error": "Screen capture plugin not loaded"}
            screenshot = await screen_plugin.capture()
            return {
                "data": screenshot.data[:100] + "...",
                "width": screenshot.width,
                "height": screenshot.height,
                "timestamp": screenshot.timestamp,
            }

        @app.get("/api/v1/config")
        async def get_config() -> dict[str, Any]:
            return self._config.model_dump()

        @app.websocket("/ws/v1/events")
        async def websocket_events(websocket: WebSocket) -> None:
            await websocket.accept()
            self._active_websockets.add(websocket)
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "task.start":
                        task = data.get("task", "")
                        task_id = str(uuid.uuid4())[:8]
                        await websocket.send_json({
                            "type": "task.created",
                            "task_id": task_id,
                        })
                        asyncio.create_task(
                            self._run_task_ws(task_id, task, websocket)
                        )
                    elif data.get("type") == "task.cancel":
                        task_id = data.get("task_id", "")
                        await websocket.send_json({
                            "type": "task.cancelled",
                            "task_id": task_id,
                        })
            except WebSocketDisconnect:
                self._active_websockets.discard(websocket)

        self._app = app
        return app

    async def _initialize_plugins(self) -> None:
        """
        Initialize and load all plugins.
        """
        from src.plugins.screen.mss_capture import MssScreenPlugin
        from src.plugins.input.pyautogui_input import PyAutoGuiInputPlugin
        from src.plugins.safety.guardrail import SafetyGuardrailPlugin
        from src.plugins.recorder.action_recorder import ActionRecorderPlugin

        config_dict = self._config.model_dump()
        self._plugin_manager = PluginManager(config=config_dict)

        screen = MssScreenPlugin()
        input_ctrl = PyAutoGuiInputPlugin()
        safety = SafetyGuardrailPlugin()
        recorder = ActionRecorderPlugin()

        await screen.initialize(config_dict.get("screen", {}))
        await input_ctrl.initialize(config_dict.get("input", {}))
        await safety.initialize(config_dict.get("safety", {}))
        await recorder.initialize(config_dict.get("recording", {}))

        ai_plugin = await self._create_ai_plugin(config_dict)

        for plugin in [screen, input_ctrl, safety, recorder, ai_plugin]:
            self._plugin_manager._plugins[plugin.name] = plugin
            self._plugin_manager._pm.register(plugin, name=plugin.name)

    async def _create_ai_plugin(self, config_dict: dict) -> Any:
        """
        Create the AI backend plugin based on configuration.

        Args:
            config_dict: Configuration dictionary.

        Returns:
            Initialized AI plugin instance.
        """
        backend = self._config.ai.default_backend
        ai_config = config_dict.get("ai", {}).get("backends", {}).get(backend, {})

        if backend == "anthropic":
            from src.adapters.anthropic_adapter import AnthropicAdapter
            plugin = AnthropicAdapter()
        elif backend == "ollama":
            from src.adapters.ollama_adapter import OllamaAdapter
            plugin = OllamaAdapter()
        else:
            from src.adapters.openai_adapter import OpenAIAdapter
            plugin = OpenAIAdapter()

        await plugin.initialize(ai_config)
        return plugin

    async def _run_task(self, task_id: str, request: Any) -> None:
        """
        Execute a task and update its status.

        Args:
            task_id: Unique task identifier.
            request: Task request with parameters.
        """
        self._tasks[task_id]["status"] = "running"

        if request.show_cursor:
            self._virtual_cursor.start()

        loop = self._create_action_loop()

        def on_progress(event: dict) -> None:
            self._tasks[task_id]["last_action"] = event
            if request.show_cursor:
                self._virtual_cursor.show_action(event.get("action", {}))
                self._virtual_cursor.set_status(
                    f"Iteration {event.get('iteration', '?')} | "
                    f"Action: {event.get('action', {}).get('type', '?')}"
                )

        result = await loop.run(request.task)

        self._tasks[task_id]["status"] = "completed" if result.get("success") else "failed"
        self._tasks[task_id]["result"] = result

        if request.show_cursor:
            self._virtual_cursor.set_status(
                f"Task {'completed' if result.get('success') else 'failed'}"
            )

    async def _run_task_ws(self, task_id: str, task: str, websocket: Any) -> None:
        """
        Execute a task with WebSocket progress streaming.

        Args:
            task_id: Unique task identifier.
            task: Task description.
            websocket: WebSocket connection for streaming.
        """
        loop = self._create_action_loop()

        def on_progress(event: dict) -> None:
            try:
                asyncio.create_task(websocket.send_json({
                    "type": "task.progress",
                    "task_id": task_id,
                    **event,
                }))
            except Exception:
                pass

        result = await loop.run(task)

        try:
            await websocket.send_json({
                "type": "task.completed" if result.get("success") else "task.failed",
                "task_id": task_id,
                "result": result,
            })
        except Exception:
            pass

    def _create_action_loop(self) -> EnhancedActionLoop:
        """
        Create an EnhancedActionLoop with all subsystems.

        Returns:
            Configured EnhancedActionLoop instance.
        """
        smart_wait = SmartWait()
        visual_verifier = VisualVerifier(smart_wait=smart_wait)
        correction_engine = SelfCorrectionEngine()

        return EnhancedActionLoop(
            plugin_manager=self._plugin_manager,
            max_iterations=self._config.core.max_iterations,
            smart_wait=smart_wait,
            visual_verifier=visual_verifier,
            correction_engine=correction_engine,
        )

    def run(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        """
        Start the API server.

        Args:
            host: Bind host address.
            port: Bind port number.
        """
        import uvicorn

        app = self.create_app()
        uvicorn.run(app, host=host, port=port, log_level="info")
