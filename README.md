# Computer Use Plugin

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-117%20passing-green.svg)]()

A modular, plugin-based AI agent system that enables AI models to interact with computer GUIs the same way humans do — by seeing screens, clicking buttons, typing text, scrolling, and navigating applications.

Supports **OpenAI CUA**, **Anthropic Claude**, and **local Ollama models** through a unified plugin architecture. Can be used as a Python library, CLI tool, REST API server, or **Claude Desktop MCP server**.

---

## Features

- 🖥️ **Screen Capture** — Cross-platform screenshots with multi-monitor support
- 🖱️ **Input Control** — Mouse clicks, drags, scrolling, keyboard typing, hotkeys
- 🧠 **Multi-Model AI** — OpenAI (CUA), Anthropic (Claude), Ollama (local vision models)
- 🔌 **Plugin Architecture** — Every capability is a pluggable, swappable module
- 🛡️ **Safety Guardrails** — 4-level validation: static rules, dynamic checks, human confirmation, audit trail
- ✅ **Visual Verification** — Confirms every action's effect; self-corrects on failure
- ⏱️ **Smart Wait** — Detects UI stability instead of fixed delays (faster than humans)
- 📹 **Action Recording** — Record and replay action sequences
- 🌐 **REST API + WebSocket** — HTTP endpoints and real-time event streaming
- 💬 **Claude Desktop** — MCP server for direct integration with Claude Desktop

---

## Installation

```bash
# Clone the repository
git clone https://github.com/akartb/computer-use.git
cd computer-use

# Install dependencies
pip install -e .

# Or with dev dependencies
pip install -e ".[dev]"
```

---

## Quick Start

### CLI

```bash
# Run a task with OpenAI (requires OPENAI_API_KEY)
computer-use run "Open Notepad and type 'Hello World'"

# Run with Anthropic Claude
computer-use run --backend anthropic "Open Calculator"

# Run with a local Ollama model
computer-use run --backend ollama "Click the Start button"

# Run in auto mode (skip confirmations)
computer-use run --safety auto "Open Chrome"

# Capture a screenshot
computer-use screenshot --output desktop.png

# List discovered plugins
computer-use plugins
```

### Python SDK

```python
import asyncio
from src.core.config import load_config
from src.core.enhanced_loop import EnhancedActionLoop
from src.core.plugin_manager import PluginManager

async def main():
    config = load_config()
    pm = PluginManager()
    pm.discover_plugins()
    await pm.load_all()

    loop = EnhancedActionLoop(plugin_manager=pm)
    result = await loop.run("Click the Start button")
    print(f"Completed: {result['success']}")

    await pm.teardown_all()

asyncio.run(main())
```

### Claude Desktop (MCP)

Add to your `claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "computer-use": {
            "command": "python",
            "args": ["-m", "src.mcp_server"],
            "cwd": "/path/to/computer-use"
        }
    }
}
```

Then chat with Claude Desktop:
- "Take a screenshot of my desktop"
- "Click at position (500, 300)"
- "Type 'Hello World' and press enter"
- "Scroll down to see more content"

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│          (CLI / Python SDK / REST API / MCP Server)         │
├─────────────────────────────────────────────────────────────┤
│                    Core Engine Layer                         │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ Action Loop │  │  Smart Wait  │  │  Context Manager │   │
│  │ Orchestrator│  │  + Verify    │  │                  │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│                   Plugin Manager Layer                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Screen   │ │  Input   │ │   AI     │ │   Safety     │  │
│  │ Capture  │ │ Control  │ │ Backend  │ │  Guardrail   │  │
│  │ Plugin   │ │ Plugin   │ │ Plugin   │ │  Plugin      │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                     Operating System                         │
└─────────────────────────────────────────────────────────────┘
```

The core loop: **Observe → Reason → Act → Verify → Correct**

1. **Observe**: Capture screenshot of current screen
2. **Reason**: AI model analyzes screenshot, decides next action
3. **Act**: Execute the action (click, type, scroll, etc.)
4. **Verify**: Confirm the action produced the expected change
5. **Correct**: If verification fails, retry or escalate automatically

---

## Project Structure

```
computer-use/
├── src/
│   ├── core/              # Engine: loop, context, config, verification
│   ├── plugins/           # Built-in: screen, input, safety, recorder
│   ├── adapters/          # AI: OpenAI, Anthropic, Ollama
│   ├── sdk/               # Plugin SDK: base class, hooks, types
│   ├── api/server.py      # REST + WebSocket server
│   ├── mcp_server.py      # MCP server for Claude Desktop
│   └── cli.py             # Command-line interface
├── config/default.yaml    # Configuration
├── docs/                  # Documentation
├── examples/              # Usage examples
├── tests/                 # 117 tests
└── pyproject.toml
```

---

## AI Backends

| Backend | Model | API Key Required | Local/Cloud |
|---------|-------|-----------------|-------------|
| OpenAI | `computer-use-preview` | `OPENAI_API_KEY` | ☁️ Cloud |
| Anthropic | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` | ☁️ Cloud |
| Ollama | `llama3.2-vision` (or any vision model) | No | 💻 Local |

---

## Safety Features

The safety system operates at **4 levels**:

| Level | Mechanism | Example |
|-------|-----------|---------|
| 1 | Static Rules | Blocked apps, keywords, coordinate limits |
| 2 | Dynamic Validation | Confidence thresholds, rate limiting |
| 3 | Human Confirmation | High-risk action approval dialogs |
| 4 | Audit & Rollback | Full action history with before/after screenshots |

Three safety modes: `auto` (all actions allowed), `confirm` (high-risk actions need approval), `sandbox` (all actions blocked).

---

## REST API

```bash
# Start the API server
computer-use serve --port 8765
```

```
POST /api/v1/tasks              # Create a task
GET  /api/v1/tasks/{id}         # Get task status
POST /api/v1/tasks/{id}/cancel  # Cancel a task
GET  /api/v1/plugins            # List plugins
GET  /api/v1/screenshot         # Capture a screenshot
```

WebSocket at `ws://localhost:8765/ws/v1/events` for real-time streaming.

---

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=src

# Type checking
mypy src

# Linting
ruff check src
```

---

## Example Scripts

Located in `examples/`:

- `basic_task.py` — Run a task with OpenAI
- `anthropic_backend.py` — Run with Anthropic Claude
- `ollama_backend.py` — Run with local Ollama model
- `record_and_replay.py` — Record and replay actions
- `screenshot_demo.py` — Capture screen and display info

---

## License

MIT

## Repository

https://github.com/akartb/computer-use
