# Development Guide

## Architecture Design

### 1. System Architecture Overview

The Computer Use Plugin follows a **layered plugin architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│          (IDE / Agent Framework / CLI / API)                 │
├─────────────────────────────────────────────────────────────┤
│                      API Layer                               │
│            (REST / WebSocket / Python SDK)                   │
├─────────────────────────────────────────────────────────────┤
│                    Core Engine Layer                         │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Action Loop │  │  Scheduler   │  │  Context Manager │   │
│  │ Orchestrator│  │              │  │                  │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                   Plugin Manager Layer                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Screen   │ │  Input   │ │   AI     │ │   Safety     │  │
│  │ Capture  │ │ Control  │ │ Backend  │ │  Guardrail   │  │
│  │ Plugin   │ │ Plugin   │ │ Plugin   │ │  Plugin      │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                   Platform Abstraction Layer                 │
│        (Windows / macOS / Linux Adapters)                    │
├─────────────────────────────────────────────────────────────┤
│                     Operating System                         │
└─────────────────────────────────────────────────────────────┘
```

### 2. Core Components

#### 2.1 Action Loop Orchestrator

The heart of the system. Manages the continuous Observe → Reason → Act cycle:

```python
class ActionLoop:
    """Orchestrates the observe-reason-act cycle."""

    async def run(self, task: str, max_iterations: int = 50) -> TaskResult:
        context = self.context_manager.create(task)
        for i in range(max_iterations):
            screenshot = await self.screen_plugin.capture()
            action = await self.ai_plugin.reason(context, screenshot)
            if action.type == "done":
                return TaskResult(success=True, history=context.history)
            validated_action = await self.safety_plugin.validate(action, context)
            await self.input_plugin.execute(validated_action)
            context.update(screenshot, action)
        return TaskResult(success=False, reason="max_iterations_reached")
```

#### 2.2 Plugin Manager

Discovers, loads, and manages plugins using a hook-based system:

```python
class PluginManager:
    """Manages plugin lifecycle: discovery, loading, configuration, teardown."""

    def discover_plugins(self, plugin_dirs) -> list[PluginInfo]: ...
    async def load_plugin(self, plugin_name, config) -> BasePlugin: ...
    async def unload_plugin(self, plugin_name) -> None: ...
    async def load_all(self) -> list[BasePlugin]: ...
    async def teardown_all(self) -> None: ...
```

#### 2.3 Context Manager

Maintains execution state across the action loop, including conversation history, screenshots, actions taken, and metadata.

### 3. Plugin Interface Specification

All plugins must implement the `BasePlugin` interface:

```python
class BasePlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    async def initialize(self, config: dict) -> None: ...

    @abstractmethod
    async def teardown(self) -> None: ...
```

#### 3.1 Screen Capture Plugin Interface

```python
class ScreenCapturePlugin(BasePlugin):
    async def capture(self, monitor=0, region=None) -> Screenshot: ...
    async def get_display_info(self) -> list[DisplayInfo]: ...
```

#### 3.2 Input Control Plugin Interface

```python
class InputControlPlugin(BasePlugin):
    async def click(self, x, y, button="left", clicks=1) -> None: ...
    async def type_text(self, text, interval=0.02) -> None: ...
    async def key_press(self, keys) -> None: ...
    async def scroll(self, x, y, direction, amount=3) -> None: ...
    async def drag(self, start_x, start_y, end_x, end_y, duration=0.5) -> None: ...
```

#### 3.3 AI Backend Plugin Interface

```python
class AIBackendPlugin(BasePlugin):
    async def reason(self, context, screenshot) -> Action: ...
    def get_supported_actions(self) -> list[str]: ...
```

#### 3.4 Safety Guardrail Plugin Interface

```python
class SafetyGuardrailPlugin(BasePlugin):
    async def validate(self, action, context) -> Action: ...
    async def check_permission(self, action) -> bool: ...
```

### 4. Action Type System

All actions are represented as structured data with pydantic validation:

- **ClickAction**: Mouse click at (x, y) with button and clicks
- **TypeAction**: Keyboard text input
- **KeyPressAction**: Key combinations
- **ScrollAction**: Mouse scroll at position
- **DragAction**: Mouse drag from start to end
- **WaitAction**: Pause execution
- **ScreenshotAction**: Request fresh screenshot
- **DoneAction**: Task completion signal

### 5. Model Adapter Pattern

Each AI model provider has an adapter that translates between the unified Action format and the provider's API. Implemented adapters:

- **OpenAIAdapter**: computer-use-preview model via Responses API
- **AnthropicAdapter**: Claude computer_use tool via Messages API
- **OllamaAdapter**: Local vision models via Ollama's OpenAI-compatible API

### 6. Safety System Design

The safety system operates at multiple levels:

```
Level 1: Static Rules
  - Blocked applications list
  - Blocked UI elements
  - Coordinate range restrictions

Level 2: Dynamic Validation
  - Context-aware action assessment
  - Confidence threshold enforcement
  - Rate limiting

Level 3: Human Confirmation
  - High-risk action approval
  - First-time application interaction
  - Destructive operation confirmation

Level 4: Audit & Rollback
  - Full action history logging
  - Screenshot before/after each action
  - State snapshot for rollback
```

### 7. Configuration System

YAML-based configuration with pydantic validation, environment variable substitution, and sensible defaults. See `config/default.yaml`.

---

## Development Phases

### Phase 1: Foundation (Week 1-2)

| Task | Description | Priority |
|---|---|---|
| Project scaffolding | Initialize Python project with pyproject.toml | P0 |
| Plugin system core | Implement BasePlugin, PluginManager, hooks | P0 |
| Screen capture | Cross-platform screenshot with mss | P0 |
| Input control | Mouse & keyboard with pyautogui | P0 |
| Action type system | Define all Action dataclasses | P0 |

### Phase 2: Intelligence (Week 3-4)

| Task | Description | Priority |
|---|---|---|
| OpenAI adapter | Implement computer-use-preview adapter | P0 |
| Anthropic adapter | Implement Claude computer use adapter | P0 |
| Action loop orchestrator | Core observe-reason-act loop | P0 |
| Context manager | Execution state management | P0 |
| Ollama adapter | Local model support | P1 |

### Phase 3: Safety & Polish (Week 5-6)

| Task | Description | Priority |
|---|---|---|
| Safety guardrail | Multi-level safety system | P0 |
| Configuration | YAML config with validation | P0 |
| Action recorder | Record and replay actions | P1 |
| REST API | HTTP API for external integration | P1 |
| WebSocket | Real-time streaming API | P1 |

### Phase 4: Ecosystem (Week 7-8)

| Task | Description | Priority |
|---|---|---|
| Plugin SDK docs | Guide for third-party development | P1 |
| Example plugins | Browser automation, file management | P1 |
| CLI tool | Command-line interface | P1 |
| Integration tests | End-to-end test suite | P0 |
| Performance optimization | Screenshot compression, action batching | P2 |

---

## Development Standards

### Code Style

- Python 3.11+ with type hints everywhere
- Use `async/await` for all I/O operations
- Follow PEP 8 with line length 120
- Use `ruff` for linting and `mypy` for type checking

### Testing Standards

- Unit test coverage > 80%
- Every plugin must have integration tests
- Use `pytest` with `pytest-asyncio`
- Mock AI backends in tests
- Safety tests must cover all guardrail levels

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| Python | >=3.11 | Runtime |
| mss | >=9.0 | Screen capture |
| Pillow | >=10.0 | Image processing |
| pyautogui | >=0.9 | Input simulation |
| pynput | >=1.7 | Alternative input |
| pluggy | >=1.3 | Plugin system |
| pydantic | >=2.0 | Data validation |
| openai | >=1.0 | OpenAI API |
| anthropic | >=0.30 | Anthropic API |
| pyyaml | >=6.0 | Configuration |
| mcp | >=1.0 | Claude Desktop MCP |

## API Design

### REST API Endpoints

```
POST   /api/v1/tasks              # Create a new task
GET    /api/v1/tasks/{id}         # Get task status
POST   /api/v1/tasks/{id}/cancel  # Cancel a running task
GET    /api/v1/tasks/{id}/history # Get action history
GET    /api/v1/plugins            # List loaded plugins
GET    /api/v1/screenshot         # Capture current screen
POST   /api/v1/action             # Execute a single action
GET    /api/v1/config             # Get current config
PUT    /api/v1/config             # Update config
```

### WebSocket Events

```
Client → Server:
  task.start     { "task": "..." }
  task.cancel    { "task_id": "..." }
  action.confirm { "action_id": "...", "approved": true }
  action.reject  { "action_id": "..." }

Server → Client:
  task.created     { "task_id": "..." }
  task.progress    { "iteration": N, "action": {...}, "screenshot": "base64..." }
  task.completed   { "task_id": "...", "summary": "..." }
  task.failed      { "task_id": "...", "error": "..." }
  action.pending   { "action_id": "...", "reason": "requires confirmation" }
  screenshot       { "data": "base64...", "timestamp": "..." }
```
