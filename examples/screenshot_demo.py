"""
Example: Taking a screenshot and capturing display information.

Demonstrates the screen capture plugin in isolation.
"""

import asyncio

from src.core.config import load_config
from src.plugins.screen.mss_capture import MssScreenPlugin


async def main() -> None:
    config = load_config()

    plugin = MssScreenPlugin()
    await plugin.initialize(config.screen.model_dump())

    # Get display information
    print("Connected displays:")
    displays = await plugin.get_display_info()
    for d in displays:
        print(f"  Monitor {d.index}: {d.width}x{d.height} at ({d.x}, {d.y}) "
              f"{'(primary)' if d.is_primary else ''}")

    # Capture primary monitor
    print("\nCapturing primary monitor...")
    screenshot = await plugin.capture(monitor=0)
    print(f"  Size: {screenshot.width}x{screenshot.height}")
    print(f"  Data length: {len(screenshot.data)} chars (base64)")
    print(f"  Timestamp: {screenshot.timestamp}")

    # Save to file
    import base64
    from pathlib import Path

    output_path = Path("screenshot_example.png")
    output_path.write_bytes(base64.b64decode(screenshot.data))
    print(f"\nSaved to: {output_path}")

    await plugin.teardown()


if __name__ == "__main__":
    asyncio.run(main())
