"""
Example: Using the Anthropic Claude backend.

Demonstrates how to switch between AI backends for computer use.
"""

import asyncio
import os

from src.core.config import load_config
from src.core.enhanced_loop import EnhancedActionLoop
from src.core.plugin_manager import PluginManager
from src.core.self_correct import SelfCorrectionEngine
from src.core.smart_wait import SmartWait
from src.core.visual_verify import VisualVerifier


async def main() -> None:
    # Set your Anthropic API key
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-your-key-here"

    config = load_config()
    config_dict = config.model_dump()

    pm = PluginManager(config=config_dict)
    pm.discover_plugins()

    from src.plugins.screen.mss_capture import MssScreenPlugin
    from src.plugins.input.pyautogui_input import PyAutoGuiInputPlugin
    from src.plugins.safety.guardrail import SafetyGuardrailPlugin
    from src.adapters.anthropic_adapter import AnthropicAdapter

    screen = MssScreenPlugin()
    input_ctrl = PyAutoGuiInputPlugin()
    safety = SafetyGuardrailPlugin()
    ai = AnthropicAdapter()

    await screen.initialize(config_dict.get("screen", {}))
    await input_ctrl.initialize(config_dict.get("input", {}))
    await safety.initialize(config_dict.get("safety", {}))
    await ai.initialize(config_dict.get("ai", {}).get("backends", {}).get("anthropic", {}))

    for plugin in [screen, input_ctrl, safety, ai]:
        pm._plugins[plugin.name] = plugin
        pm._pm.register(plugin, name=plugin.name)

    loop = EnhancedActionLoop(
        plugin_manager=pm,
        max_iterations=30,
        smart_wait=SmartWait(min_wait=0.3, max_wait=15.0),
        visual_verifier=VisualVerifier(),
        correction_engine=SelfCorrectionEngine(),
    )

    task = "Open the browser and navigate to wikipedia.org"
    print(f"Task: {task}")
    result = await loop.run(task, config=config_dict)

    print(f"\nDone: {result.get('success')}, iterations={result.get('total_iterations')}")
    await pm.teardown_all()


if __name__ == "__main__":
    asyncio.run(main())
