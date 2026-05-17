"""
Command-line interface for Computer Use Plugin.

Provides a simple CLI to run tasks:
    computer-use run "Open Chrome and search for cats"
    computer-use run --backend anthropic "Create a new document"
    computer-use run --safety auto "Click the Start button"
    computer-use screenshot
    computer-use plugins
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from src.core.config import AppConfig, load_config
from src.core.enhanced_loop import EnhancedActionLoop
from src.core.plugin_manager import PluginManager
from src.core.self_correct import SelfCorrectionEngine
from src.core.smart_wait import SmartWait
from src.core.visual_verify import VisualVerifier
from src.core.virtual_cursor import VirtualCursorOverlay


def setup_logging(level: str = "INFO") -> None:
    """
    Configure logging with a clean format.

    Args:
        level: Log level name.
    """
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def run_task(
    task: str,
    config: AppConfig,
    backend: str | None = None,
    safety_mode: str | None = None,
    max_iterations: int | None = None,
    headless: bool = False,
    show_cursor: bool = True,
) -> dict[str, Any]:
    """
    Execute a task using the enhanced action loop.

    Args:
        task: Natural language task description.
        config: Application configuration.
        backend: AI backend override ('openai', 'anthropic', 'ollama').
        safety_mode: Safety mode override ('auto', 'confirm', 'sandbox').
        max_iterations: Max loop iterations override.
        headless: If True, disable visual verification and smart wait.

    Returns:
        Task result dictionary.
    """
    if backend:
        config.ai.default_backend = backend
    if safety_mode:
        config.safety.mode = safety_mode
    if max_iterations:
        config.core.max_iterations = max_iterations

    plugin_config = config.model_dump()

    pm = PluginManager(config=plugin_config)

    pm.discover_plugins()

    screen_plugin = None
    input_plugin = None
    safety_plugin = None
    ai_plugin = None

    from src.plugins.screen.mss_capture import MssScreenPlugin
    from src.plugins.input.pyautogui_input import PyAutoGuiInputPlugin
    from src.plugins.safety.guardrail import SafetyGuardrailPlugin

    screen_plugin = MssScreenPlugin()
    input_plugin = PyAutoGuiInputPlugin()
    safety_plugin = SafetyGuardrailPlugin()

    if config.ai.default_backend == "anthropic":
        from src.adapters.anthropic_adapter import AnthropicAdapter
        ai_plugin = AnthropicAdapter()
    elif config.ai.default_backend == "ollama":
        from src.adapters.ollama_adapter import OllamaAdapter
        ai_plugin = OllamaAdapter()
    else:
        from src.adapters.openai_adapter import OpenAIAdapter
        ai_plugin = OpenAIAdapter()

    await screen_plugin.initialize(plugin_config.get("screen", {}))
    await input_plugin.initialize(plugin_config.get("input", {}))
    await safety_plugin.initialize(plugin_config.get("safety", {}))

    ai_config = plugin_config.get("ai", {}).get("backends", {}).get(config.ai.default_backend, {})
    await ai_plugin.initialize(ai_config)

    pm._plugins[screen_plugin.name] = screen_plugin
    pm._plugins[input_plugin.name] = input_plugin
    pm._plugins[safety_plugin.name] = safety_plugin
    pm._plugins[ai_plugin.name] = ai_plugin

    pm._pm.register(screen_plugin, name=screen_plugin.name)
    pm._pm.register(input_plugin, name=input_plugin.name)
    pm._pm.register(safety_plugin, name=safety_plugin.name)
    pm._pm.register(ai_plugin, name=ai_plugin.name)

    if headless:
        loop = EnhancedActionLoop(
            plugin_manager=pm,
            max_iterations=config.core.max_iterations,
            smart_wait=SmartWait(min_wait=0.05, max_wait=3.0),
        )
    else:
        smart_wait = SmartWait(
            stability_threshold=0.005,
            check_interval=0.1,
            min_wait=0.2,
            max_wait=10.0,
        )
        visual_verifier = VisualVerifier(smart_wait=smart_wait)
        correction_engine = SelfCorrectionEngine(max_total_retries=10)

        loop = EnhancedActionLoop(
            plugin_manager=pm,
            max_iterations=config.core.max_iterations,
            smart_wait=smart_wait,
            visual_verifier=visual_verifier,
            correction_engine=correction_engine,
        )

    cursor = None
    if show_cursor and not headless:
        cursor = VirtualCursorOverlay()
        cursor.start()
        cursor.set_status(f"Starting: {task[:50]}")

    def on_progress(event: dict) -> None:
        if cursor:
            cursor.show_action(event.get("action", {}))
            cursor.set_status(
                f"Iter {event.get('iteration', '?')}/{config.core.max_iterations} | "
                f"{event.get('action', {}).get('type', '?')} | "
                f"Retries: {event.get('total_retries', 0)}"
            )

    loop._on_progress = on_progress

    result = await loop.run(task, config=plugin_config)

    if cursor:
        status = "completed" if result.get("success") else "failed"
        cursor.set_status(f"Task {status}")
        await asyncio.sleep(1.5)
        cursor.stop()

    await pm.teardown_all()

    return result


def cmd_run(args: argparse.Namespace) -> None:
    """
    Handle the 'run' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = load_config(args.config)
    setup_logging(config.logging.level)

    logger = logging.getLogger("cli")
    logger.info("Running task: %s", args.task)

    if args.dry_run:
        print(f"[DRY RUN] Task: {args.task}")
        print(f"  Backend: {args.backend or config.ai.default_backend}")
        print(f"  Safety: {args.safety or config.safety.mode}")
        print(f"  Max iterations: {args.max_iter or config.core.max_iterations}")
        return

    result = asyncio.run(run_task(
        task=args.task,
        config=config,
        backend=args.backend,
        safety_mode=args.safety,
        max_iterations=args.max_iter,
        headless=args.headless,
        show_cursor=not args.no_cursor,
    ))

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        status = "✅ SUCCESS" if result.get("success") else "❌ FAILED"
        print(f"\n{status}")
        print(f"  Task: {args.task}")
        print(f"  Iterations: {result.get('total_iterations', 0)}")
        print(f"  Retries: {result.get('total_retries', 0)}")
        print(f"  Duration: {result.get('total_duration_ms', 0):.0f}ms")
        if result.get("summary"):
            print(f"  Summary: {result['summary']}")
        if result.get("error"):
            print(f"  Error: {result['error']}")


def cmd_screenshot(args: argparse.Namespace) -> None:
    """
    Handle the 'screenshot' command.

    Args:
        args: Parsed command-line arguments.
    """
    config = load_config(args.config)
    setup_logging("WARNING")

    async def take_screenshot() -> None:
        from src.plugins.screen.mss_capture import MssScreenPlugin

        plugin = MssScreenPlugin()
        await plugin.initialize(config.screen.model_dump())
        screenshot = await plugin.capture(monitor=args.monitor)
        await plugin.teardown()

        output_path = Path(args.output) if args.output else Path("screenshot.png")
        output_path.write_bytes(
            __import__("base64").b64decode(screenshot.data),
        )
        print(f"Screenshot saved to {output_path} ({screenshot.width}x{screenshot.height})")

    asyncio.run(take_screenshot())


def cmd_plugins(args: argparse.Namespace) -> None:
    """
    Handle the 'plugins' command.

    Args:
        args: Parsed command-line arguments.
    """
    pm = PluginManager()
    discovered = pm.discover_plugins()

    if not discovered:
        print("No plugins discovered.")
        return

    print(f"Discovered {len(discovered)} plugins:")
    for info in discovered:
        print(f"  {info.name} v{info.version}: {info.description}")


def cmd_serve(args: argparse.Namespace) -> None:
    """
    Handle the 'serve' command - start the API server.

    Args:
        args: Parsed command-line arguments.
    """
    config = load_config(args.config)
    setup_logging(config.logging.level)

    from src.api.server import ComputerUseServer

    server = ComputerUseServer(config)
    print(f"Starting Computer Use API server on {args.host}:{args.port}")
    print(f"  REST API:  http://{args.host}:{args.port}/docs")
    print(f"  WebSocket: ws://{args.host}:{args.port}/ws/v1/events")
    server.run(host=args.host, port=args.port)


def cmd_replay(args: argparse.Namespace) -> None:
    """
    Handle the 'replay' command - replay a recorded action sequence.

    Args:
        args: Parsed command-line arguments.
    """
    config = load_config(args.config)
    setup_logging(config.logging.level)

    from src.plugins.recorder.action_recorder import ActionRecorderPlugin

    recording = ActionRecorderPlugin.load_recording(args.file)
    actions = recording.get("actions", [])

    if not actions:
        print("No actions found in recording.")
        return

    print(f"Replaying {len(actions)} actions from: {args.file}")
    print(f"  Original task: {recording.get('task', 'unknown')}")
    print(f"  Speed: {args.speed}x")

    async def replay_actions() -> None:
        from src.plugins.screen.mss_capture import MssScreenPlugin
        from src.plugins.input.pyautogui_input import PyAutoGuiInputPlugin

        input_plugin = PyAutoGuiInputPlugin()
        await input_plugin.initialize(config.input.model_dump())

        cursor = None
        if not args.no_cursor:
            cursor = VirtualCursorOverlay()
            cursor.start()
            cursor.set_status(f"Replay: {recording.get('task', '')[:40]}")

        for i, record in enumerate(actions):
            action = record.get("action", {})
            action_type = action.get("type", "")

            if action_type in ("done", "screenshot"):
                continue

            if cursor:
                cursor.show_action(action)
                cursor.set_status(f"Replay {i+1}/{len(actions)}: {action_type}")

            print(f"  [{i+1}/{len(actions)}] {action_type}: {action.get('parameters', {})}")

            await input_plugin.execute_action(action)

            delay = record.get("result", {}).get("duration_ms", 500) / 1000.0
            delay = delay / args.speed
            await asyncio.sleep(max(0.1, delay))

        if cursor:
            cursor.set_status("Replay completed")
            await asyncio.sleep(1.5)
            cursor.stop()

        await input_plugin.teardown()

    asyncio.run(replay_actions())
    print("Replay completed.")


def main() -> None:
    """
    Main CLI entry point.
    """
    parser = argparse.ArgumentParser(
        prog="computer-use",
        description="Computer Use Plugin - AI agent for GUI interaction",
    )
    parser.add_argument("--config", type=str, default=None, help="Path to config YAML file")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    run_parser = subparsers.add_parser("run", help="Run a task")
    run_parser.add_argument("task", type=str, help="Natural language task description")
    run_parser.add_argument("--backend", choices=["openai", "anthropic", "ollama"], default=None)
    run_parser.add_argument("--safety", choices=["auto", "confirm", "sandbox"], default=None)
    run_parser.add_argument("--max-iter", type=int, default=None)
    run_parser.add_argument("--headless", action="store_true", help="Disable visual verification")
    run_parser.add_argument("--no-cursor", action="store_true", help="Disable virtual cursor overlay")
    run_parser.add_argument("--dry-run", action="store_true", help="Show config without running")
    run_parser.add_argument("--json", action="store_true", help="Output result as JSON")

    ss_parser = subparsers.add_parser("screenshot", help="Capture a screenshot")
    ss_parser.add_argument("--monitor", type=int, default=0)
    ss_parser.add_argument("--output", type=str, default=None)

    subparsers.add_parser("plugins", help="List discovered plugins")

    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument("--host", type=str, default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8765)

    replay_parser = subparsers.add_parser("replay", help="Replay a recorded action sequence")
    replay_parser.add_argument("file", type=str, help="Path to recording JSON file")
    replay_parser.add_argument("--speed", type=float, default=1.0, help="Replay speed multiplier")
    replay_parser.add_argument("--no-cursor", action="store_true", help="Disable virtual cursor")

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "screenshot":
        cmd_screenshot(args)
    elif args.command == "plugins":
        cmd_plugins(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "replay":
        cmd_replay(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
