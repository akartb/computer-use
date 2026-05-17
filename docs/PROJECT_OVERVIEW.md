# Computer Use Plugin

A modular, plugin-based AI agent system that enables AI models to interact with computer GUIs the same way humans do — by seeing screens, clicking buttons, typing text, scrolling, and navigating applications.

Inspired by OpenAI's Computer Use (CUA model) and Anthropic's Computer Use feature, this project reimagines the concept as a **lightweight, extensible plugin architecture** rather than a monolithic service. It can be embedded into any AI agent framework, IDE, or automation platform.

---

## Core Concept

### The Action Loop

The fundamental operating principle is a continuous **Observe → Reason → Act** loop:

```
┌─────────────────────────────────────────────────┐
│                  Action Loop                     │
│                                                  │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│   │ Observe  │───▶│  Reason  │───▶│   Act    │  │
│   └──────────┘    └──────────┘    └──────────┘  │
│        ▲                               │         │
│        └───────────────────────────────┘         │
│              Updated Screenshot                  │
└─────────────────────────────────────────────────┘
```

1. **Observe**: Capture a screenshot of the current screen state
2. **Reason**: AI model analyzes the screenshot and determines the next action
3. **Act**: Execute the action (click, type, scroll, etc.)
4. **Loop**: Capture updated screenshot and repeat until task is complete

---

## Key Differentiators

| Feature | OpenAI CUA | Anthropic CU | **This Project** |
|---|---|---|---|
| Architecture | Cloud API Service | Cloud API Service | **Plugin-based** |
| Integration | Responses API | Messages API | **Any framework** |
| Model Dependency | GPT-4o/CUA only | Claude only | **Multi-model** |
| Deployment | Cloud only | Cloud only | **Local + Cloud** |
| Extensibility | Limited | Limited | **Plugin System** |
| Platform | Cloud sandbox | Cloud sandbox | **Native OS** |

---

## Project Goals

1. **Plugin-First Design**: Every capability is a pluggable module that can be swapped, extended, or replaced independently.
2. **Multi-Model Support**: Support multiple AI backends (OpenAI, Anthropic, local models via Ollama) through a unified adapter interface.
3. **Cross-Platform**: Run natively on Windows, macOS, and Linux with platform-specific optimized input controllers.
4. **Safety-First**: Built-in safety guardrails including action confirmation, sandbox mode, permission system, and rollback capabilities.
5. **Developer-Friendly**: Clean APIs, comprehensive documentation, and a plugin SDK for custom extensions.
6. **Lightweight**: Minimal dependencies, fast startup, suitable for embedding into existing applications.

---

## Target Users

- **AI Agent Developers** — Build agents that can operate computers autonomously
- **RPA Engineers** — Upgrade traditional RPA with AI-driven visual understanding
- **QA Engineers** — Automate UI testing with natural language instructions
- **Productivity Seekers** — Automate repetitive desktop workflows
- **Researchers** — Experiment with computer interaction AI models

---

## Project Scope

### In Scope

Screen capture, mouse/keyboard control, multi-monitor support, action recording and replay, safety guardrails, plugin SDK, multi-model AI backends.

### Out of Scope

OS virtualization, network-level manipulation, kernel drivers, mobile device control, browser-only automation.

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Core Language | Python 3.11+ | Plugin system, orchestration |
| Screen Capture | mss / Pillow | Cross-platform screenshots |
| Input Control | pyautogui / pynput | Mouse & keyboard simulation |
| AI Backend | OpenAI / Anthropic / Ollama | Vision & reasoning |
| Plugin System | pluggy / custom | Extensibility |
| Config | YAML / TOML | Settings management |

---

## Project Structure

```
computer-use-plugin/
├── src/
│   ├── core/                    # Core engine
│   │   ├── loop.py              # Action loop orchestrator
│   │   ├── enhanced_loop.py     # Enhanced loop with verification
│   │   ├── context.py           # Execution context
│   │   ├── config.py            # Configuration system
│   │   ├── plugin_manager.py    # Plugin discovery & loading
│   │   ├── smart_wait.py        # UI stability detection
│   │   ├── visual_verify.py     # Action result verification
│   │   ├── self_correct.py      # Failure recovery engine
│   │   └── virtual_cursor.py    # Visual cursor overlay
│   ├── plugins/
│   │   ├── screen/              # Screen capture plugin
│   │   ├── input/               # Input control plugin
│   │   ├── ai/                  # AI backend plugins
│   │   ├── safety/              # Safety guardrail plugin
│   │   └── recorder/            # Action recorder plugin
│   ├── adapters/                # Model adapters
│   │   ├── openai_adapter.py    # OpenAI CUA adapter
│   │   ├── anthropic_adapter.py # Anthropic adapter
│   │   └── ollama_adapter.py    # Local model adapter
│   ├── sdk/                     # Plugin SDK
│   │   ├── base.py              # Base plugin class
│   │   ├── hooks.py             # Plugin hooks
│   │   └── types.py             # Type definitions
│   ├── mcp_server.py            # MCP Server for Claude Desktop
│   ├── api/server.py            # REST + WebSocket server
│   └── cli.py                   # CLI
├── config/
│   ├── default.yaml             # Default settings
│   └── claude_desktop_config.json
├── docs/
├── examples/
├── tests/
└── pyproject.toml
```

---

## Progress Log

| Date | Milestone | Status |
|---|---|---|
| 2026-04-19 | Project planning & documentation | ✅ |
| 2026-04-19 | Project scaffolding | ✅ |
| 2026-04-19 | Action type system (8 types) | ✅ |
| 2026-04-19 | Plugin system core | ✅ |
| 2026-04-19 | Screen capture plugin | ✅ |
| 2026-04-19 | Input control plugin | ✅ |
| 2026-04-19 | Core engine (ActionLoop, Context) | ✅ |
| 2026-04-19 | Configuration system | ✅ |
| 2026-04-19 | Safety guardrail plugin | ✅ |
| 2026-04-19 | OpenAI CUA adapter | ✅ |
| 2026-04-19 | Unit tests (31 tests) | ✅ |
| 2026-04-19 | Anthropic adapter | ✅ |
| 2026-04-19 | Smart Wait system | ✅ |
| 2026-04-19 | Visual Verification system | ✅ |
| 2026-04-19 | Self-Correction engine | ✅ |
| 2026-04-19 | Enhanced ActionLoop | ✅ |
| 2026-04-19 | CLI tool | ✅ |
| 2026-04-19 | Phase 2 tests (61 tests) | ✅ |
| 2026-04-19 | Virtual Cursor Overlay | ✅ |
| 2026-04-19 | Action Recorder Plugin | ✅ |
| 2026-04-19 | REST API + WebSocket | ✅ |
| 2026-04-19 | CLI integration | ✅ |
| 2026-04-19 | Phase 3 tests (83 tests) | ✅ |
| 2026-05-17 | Ollama adapter (local models) | ✅ |
| 2026-05-17 | Integration tests (117 total) | ✅ |
| 2026-05-17 | Example scripts (5 examples) | ✅ |
| 2026-05-17 | Pillow deprecation fix | ✅ |
| 2026-05-17 | MCP Server for Claude Desktop | ✅ |
