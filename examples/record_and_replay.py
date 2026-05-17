"""
Example: Recording and replaying action sequences.

Shows how to record actions during a task and replay them later.
"""

import asyncio
import json

from src.core.config import load_config
from src.plugins.recorder.action_recorder import ActionRecorderPlugin
from src.plugins.input.pyautogui_input import PyAutoGuiInputPlugin


async def demo_recording() -> None:
    """Demonstrate how to manually record actions for later replay."""
    recorder = ActionRecorderPlugin()
    await recorder.initialize({"output_dir": "./recordings", "auto_save": False})

    recorder.on_task_start("Demo recording", {"task_id": "demo1"})

    # Simulate a few actions (in real use, these come from the AI action loop)
    actions = [
        {"type": "click", "parameters": {"x": 500, "y": 300, "button": "left", "clicks": 1}},
        {"type": "type", "parameters": {"text": "Hello World"}},
        {"type": "key_press", "parameters": {"keys": ["enter"]}},
    ]

    for i, action in enumerate(actions):
        recorder.on_action_completed(
            action=action,
            result={"success": True, "duration_ms": 50.0},
            context={"iteration": i + 1},
        )

    recorder.on_task_end("Demo recording", {"success": True, "total_iterations": 3}, {})

    # Save to file
    path = recorder.save_recording()
    print(f"Recording saved to: {path}")

    # Export actions for replay
    export = recorder.export_actions()
    print(f"Exported {len(export)} actions for replay:")
    for act in export:
        print(f"  {act['type']}: {act['parameters']}")


async def demo_replay(recording_path: str) -> None:
    """Demonstrate replaying a saved recording."""
    from src.core.virtual_cursor import VirtualCursorOverlay

    recording = ActionRecorderPlugin.load_recording(recording_path)
    print(f"Loaded recording: {recording['task']}")
    print(f"Actions: {len(recording['actions'])}")

    input_plugin = PyAutoGuiInputPlugin()
    await input_plugin.initialize({})

    cursor = VirtualCursorOverlay()
    cursor.start()

    for record in recording["actions"]:
        action = record["action"]
        print(f"  Replaying: {action['type']} - {action.get('parameters', {})}")
        cursor.show_action(action)
        await input_plugin.execute_action(action)
        await asyncio.sleep(0.5)

    cursor.stop()
    await input_plugin.teardown()
    print("Replay complete.")


async def main() -> None:
    print("=" * 40)
    print("Demo: Recording actions")
    print("=" * 40)
    await demo_recording()

    print()
    print("=" * 40)
    print("Demo: Replay (dry run - no actual actions)")
    print("=" * 40)

    import glob as g
    files = g.glob("./recordings/*.json")
    if files:
        newest = max(files)
        recording = ActionRecorderPlugin.load_recording(newest)
        print(f"Would replay: {recording['task']} ({len(recording['actions'])} actions)")
        for record in recording["actions"]:
            a = record["action"]
            print(f"  {a['type']}: {a.get('parameters', {})}")
    else:
        print("No recordings found.")


if __name__ == "__main__":
    asyncio.run(main())
