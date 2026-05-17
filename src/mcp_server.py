"""
MCP Server for Computer Use Plugin — integrates with Claude Desktop.

Exposes computer control tools (screenshot, click, type, scroll, etc.)
through the Model Context Protocol (MCP) stdio transport.

Usage with Claude Desktop — add to claude_desktop_config.json:
{
    "mcpServers": {
        "computer-use": {
            "command": "python",
            "args": ["-m", "src.mcp_server"],
            "cwd": "<project-dir>"
        }
    }
}
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

logger = logging.getLogger("computer-use-mcp")

# ──────────────────────────────────────────────
#  Direct implementations (no plugin overhead)
# ──────────────────────────────────────────────


def _capture_screen(monitor: int = 0) -> dict[str, Any]:
    """Capture a screenshot and return base64 PNG + metadata."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor >= len(monitors):
            monitor = 0
        raw = sct.grab(monitors[monitor])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        w, h = img.size

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    return {"data": b64, "width": w, "height": h, "monitor": monitor}


def _get_display_info() -> list[dict[str, Any]]:
    """Return information about all connected displays."""
    import mss

    displays: list[dict[str, Any]] = []
    with mss.mss() as sct:
        for i, mon in enumerate(sct.monitors[1:], start=0):
            displays.append({
                "index": i,
                "width": mon["width"],
                "height": mon["height"],
                "x": mon["left"],
                "y": mon["top"],
                "is_primary": i == 0,
            })
    return displays


def _mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
    """Execute a mouse click at coordinates."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.moveTo(x, y, duration=0.3)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    return {"success": True, "action": f"{button}_click", "x": x, "y": y, "clicks": clicks}


def _mouse_move(x: int, y: int, duration: float = 0.3) -> dict[str, Any]:
    """Move mouse cursor to coordinates."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.moveTo(x, y, duration=duration)
    return {"success": True, "action": "move", "x": x, "y": y}


def _type_text(text: str, interval: float = 0.02) -> dict[str, Any]:
    """Type text character by character."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.typewrite(text, interval=interval)
    return {"success": True, "action": "type", "text": text}


def _key_press(keys: str) -> dict[str, Any]:
    """Press a key combination like 'ctrl+c' or a single key like 'enter'."""
    import pyautogui

    pyautogui.FAILSAFE = True
    parts = [k.strip() for k in keys.split("+")]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return {"success": True, "action": "key_press", "keys": parts}


def _scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> dict[str, Any]:
    """Scroll at the specified coordinates."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.moveTo(x, y, duration=0.2)
    scroll_amount = amount if direction == "down" else -amount
    pyautogui.scroll(scroll_amount, x=x, y=y)
    return {"success": True, "action": "scroll", "x": x, "y": y, "direction": direction, "amount": amount}


def _drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> dict[str, Any]:
    """Drag from start to end position."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.moveTo(start_x, start_y, duration=0.3)
    pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
    return {"success": True, "action": "drag", "start_x": start_x, "start_y": start_y, "end_x": end_x, "end_y": end_y}


def _wait(duration: float = 1.0) -> dict[str, Any]:
    """Wait for a duration."""
    time.sleep(duration)
    return {"success": True, "action": "wait", "duration": duration}


def _current_mouse_position() -> dict[str, Any]:
    """Get current mouse position."""
    import pyautogui

    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


def _screen_size() -> dict[str, Any]:
    """Get primary screen dimensions."""
    import pyautogui

    w, h = pyautogui.size()
    return {"width": w, "height": h}


# ──────────────────────────────────────────────
#  MCP Server
# ──────────────────────────────────────────────

app = Server("computer-use")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List all available computer-use tools."""
    return [
        Tool(
            name="screenshot",
            description="Capture a screenshot of the current screen. Returns base64-encoded PNG image with width and height metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "monitor": {
                        "type": "integer",
                        "description": "Monitor index to capture (0 = primary, 1 = secondary, etc.)",
                        "default": 0,
                    },
                },
            },
        ),
        Tool(
            name="get_screen_size",
            description="Get the primary screen width and height in pixels.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_display_info",
            description="Get information about all connected displays (resolution, position, primary status).",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_mouse_position",
            description="Get the current mouse cursor (x, y) coordinates.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="mouse_move",
            description="Move the mouse cursor to the specified (x, y) coordinates smoothly.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Horizontal pixel coordinate (0 = left edge)"},
                    "y": {"type": "integer", "description": "Vertical pixel coordinate (0 = top edge)"},
                    "duration": {
                        "type": "number",
                        "description": "Movement duration in seconds (default: 0.3)",
                        "default": 0.3,
                    },
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="click",
            description="Click the mouse at specified (x, y) coordinates. Supports left/right/middle button and single/double/triple clicks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Horizontal pixel coordinate"},
                    "y": {"type": "integer", "description": "Vertical pixel coordinate"},
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button to click (default: 'left')",
                        "default": "left",
                    },
                    "clicks": {
                        "type": "integer",
                        "enum": [1, 2, 3],
                        "description": "Number of clicks: 1=single, 2=double, 3=triple (default: 1)",
                        "default": 1,
                    },
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="type_text",
            description="Type text character by character at the current keyboard cursor position.",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to type"},
                    "interval": {
                        "type": "number",
                        "description": "Delay between keystrokes in seconds (default: 0.02)",
                        "default": 0.02,
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="key_press",
            description="Press a single key or key combination. Single key: 'enter', 'tab', 'escape', etc. Combination: 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+r', etc. Use '+' to separate keys in combinations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keys": {
                        "type": "string",
                        "description": "Key or key combination, e.g. 'enter', 'ctrl+c', 'alt+tab', 'win+r'",
                    },
                },
                "required": ["keys"],
            },
        ),
        Tool(
            name="scroll",
            description="Scroll the mouse wheel at specified coordinates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Horizontal pixel coordinate"},
                    "y": {"type": "integer", "description": "Vertical pixel coordinate"},
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "Scroll direction (default: 'down')",
                        "default": "down",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "Number of scroll notches (default: 3)",
                        "default": 3,
                    },
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="drag",
            description="Mouse drag from a start position to an end position. Useful for moving windows, selecting text, drag-and-drop operations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_x": {"type": "integer", "description": "Start horizontal coordinate"},
                    "start_y": {"type": "integer", "description": "Start vertical coordinate"},
                    "end_x": {"type": "integer", "description": "End horizontal coordinate"},
                    "end_y": {"type": "integer", "description": "End vertical coordinate"},
                    "duration": {
                        "type": "number",
                        "description": "Drag duration in seconds (default: 0.5)",
                        "default": 0.5,
                    },
                },
                "required": ["start_x", "start_y", "end_x", "end_y"],
            },
        ),
        Tool(
            name="wait",
            description="Pause execution for a specified duration. Use between actions to wait for UI responses (animations, loading, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "duration": {
                        "type": "number",
                        "description": "Wait duration in seconds (default: 1.0). Max: 10.0",
                        "default": 1.0,
                    },
                },
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Handle tool invocation and return results."""

    try:
        if name == "screenshot":
            result = await asyncio.to_thread(_capture_screen, arguments.get("monitor", 0))
            return [
                TextContent(
                    type="text",
                    text=f"Screenshot captured: {result['width']}x{result['height']} on monitor {result['monitor']}",
                ),
                ImageContent(
                    type="image",
                    data=result["data"],
                    mimeType="image/png",
                ),
            ]

        elif name == "get_screen_size":
            result = await asyncio.to_thread(_screen_size)
            return [TextContent(type="text", text=f"Screen size: {result['width']} x {result['height']} pixels")]

        elif name == "get_display_info":
            result = await asyncio.to_thread(_get_display_info)
            lines = [f"{d['index']}: {d['width']}x{d['height']} at ({d['x']},{d['y']}){' [PRIMARY]' if d['is_primary'] else ''}" for d in result]
            return [TextContent(type="text", text="Displays:\n" + "\n".join(lines))]

        elif name == "get_mouse_position":
            result = await asyncio.to_thread(_current_mouse_position)
            return [TextContent(type="text", text=f"Mouse position: ({result['x']}, {result['y']})")]

        elif name == "mouse_move":
            result = await asyncio.to_thread(
                _mouse_move,
                arguments["x"],
                arguments["y"],
                arguments.get("duration", 0.3),
            )
            return [TextContent(type="text", text=f"Moved mouse to ({arguments['x']}, {arguments['y']})")]

        elif name == "click":
            result = await asyncio.to_thread(
                _mouse_click,
                arguments["x"],
                arguments["y"],
                arguments.get("button", "left"),
                arguments.get("clicks", 1),
            )
            label = f"{arguments.get('button', 'left')}-click"
            if arguments.get("clicks", 1) == 2:
                label = "double-click"
            elif arguments.get("clicks", 1) == 3:
                label = "triple-click"
            return [TextContent(type="text", text=f"{label} at ({arguments['x']}, {arguments['y']})")]

        elif name == "type_text":
            text = arguments["text"]
            interval = arguments.get("interval", 0.02)
            await asyncio.to_thread(_type_text, text, interval)
            return [TextContent(type="text", text=f"Typed text (length={len(text)})")]

        elif name == "key_press":
            keys = arguments["keys"]
            await asyncio.to_thread(_key_press, keys)
            return [TextContent(type="text", text=f"Pressed keys: {keys}")]

        elif name == "scroll":
            result = await asyncio.to_thread(
                _scroll,
                arguments["x"],
                arguments["y"],
                arguments.get("direction", "down"),
                arguments.get("amount", 3),
            )
            return [TextContent(
                type="text",
                text=f"Scrolled {arguments.get('direction', 'down')} x{arguments.get('amount', 3)} at ({arguments['x']}, {arguments['y']})",
            )]

        elif name == "drag":
            result = await asyncio.to_thread(
                _drag,
                arguments["start_x"],
                arguments["start_y"],
                arguments["end_x"],
                arguments["end_y"],
                arguments.get("duration", 0.5),
            )
            return [TextContent(
                type="text",
                text=f"Dragged from ({arguments['start_x']},{arguments['start_y']}) to ({arguments['end_x']},{arguments['end_y']})",
            )]

        elif name == "wait":
            duration = min(arguments.get("duration", 1.0), 10.0)
            await asyncio.to_thread(_wait, duration)
            return [TextContent(type="text", text=f"Waited {duration}s")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
        return [TextContent(type="text", text=f"Error executing '{name}': {e}")]


async def main() -> None:
    """Run the MCP server with stdio transport."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run() -> None:
    """Entry point for the MCP server."""
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())


if __name__ == "__main__":
    run()
