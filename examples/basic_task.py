"""
Example: Basic task execution with Computer Use Plugin.

This example shows how to run a simple task using the action loop.
Replace the API key placeholder with your actual API key.
"""

import asyncio
import os

from src.core.config import AppConfig, load_config
from src.core.enhanced_loop import EnhancedActionLoop
from src.core.plugin_manager import PluginManager
from src.core.self_correct import SelfCorrectionEngine
from src.core.smart_wait import SmartWait
from src.core.visual_verify import VisualVerifier


async def main() -> None:
    # Set your API key
    os.environ["OPENAI_API_KEY"] = "sk-your-key-here"

    # Load configuration
    config = load_config()
    config_dict = config.model_dump()

    # Create plugin manager and discover plugins
    pm = PluginManager(config=config_dict)
    pm.discover_plugins()

    # Manually create and register core plugins
    from src.plugins.screen.mss_capture import MssScreenPlugin
    from src.plugins.input.pyautogui_input import PyAutoGuiInputPlugin
    from src.plugins.safety.guardrail import SafetyGuardrailPlugin
    from src.adapters.openai_adapter import OpenAIAdapter

    screen = MssScreenPlugin()
    input_ctrl = PyAutoGuiInputPlugin()
    safety = SafetyGuardrailPlugin()
    ai = OpenAIAdapter()

    await screen.initialize(config_dict.get("screen", {}))
    await input_ctrl.initialize(config_dict.get("input", {}))
    await safety.initialize(config_dict.get("safety", {}))
    await ai.initialize(config_dict.get("ai", {}).get("backends", {}).get("openai", {}))

    for plugin in [screen, input_ctrl, safety, ai]:
        pm._plugins[plugin.name] = plugin
        pm._pm.register(plugin, name=plugin.name)

    # Create the enhanced action loop
    smart_wait = SmartWait(min_wait=0.2, max_wait=10.0)
    visual_verifier = VisualVerifier(smart_wait=smart_wait)
    correction_engine = SelfCorrectionEngine(max_total_retries=10)

    loop = EnhancedActionLoop(
        plugin_manager=pm,
        max_iterations=config.core.max_iterations,
        smart_wait=smart_wait,
        visual_verifier=visual_verifier,
        correction_engine=correction_engine,
    )

    # Run a task
    task = "Open Notepad and type 'Hello from Computer Use Plugin'"
    print(f"Running task: {task}")

    result = await loop.run(task, config=config_dict)

    print(f"\nResult: {'SUCCESS' if result.get('success') else 'FAILED'}")
    print(f"  Iterations: {result.get('total_iterations', 0)}")
    print(f"  Retries: {result.get('total_retries', 0)}")
    print(f"  Duration: {result.get('total_duration_ms', 0):.0f}ms")

    await pm.teardown_all()


if __name__ == "__main__":
    asyncio.run(main())
