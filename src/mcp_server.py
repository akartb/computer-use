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
import os
import subprocess
import sys
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

logger = logging.getLogger("computer-use-mcp")

# ──────────────────────────────────────────────
#  Windows API helpers — system-wide key events
#  that bypass application focus
# ──────────────────────────────────────────────

_is_windows = sys.platform == "win32"

if _is_windows:
    import ctypes
    from ctypes import wintypes

    # Virtual key codes
    VK = {
        "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "shift": 0x10,
        "ctrl": 0x11, "alt": 0x12, "escape": 0x1B, "space": 0x20,
        "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
        "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
        "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
        "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
        "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
        "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
        "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
        "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
        "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
        "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }

    KEYEVENTF_KEYUP = 0x0002

    def _send_key_event(vk_code: int, key_up: bool = False) -> None:
        """Send a low-level keyboard event via Win32 API (system-wide, bypasses app focus)."""
        flags = KEYEVENTF_KEYUP if key_up else 0
        ctypes.windll.user32.keybd_event(vk_code, 0, flags, 0)

    def _press_key_raw(vk_code: int) -> None:
        """Press and release a single key at the system level."""
        _send_key_event(vk_code, False)
        time.sleep(0.02)
        _send_key_event(vk_code, True)

    def _hold_key_raw(vk_code: int) -> None:
        """Hold down a key (caller must release it)."""
        _send_key_event(vk_code, False)

    def _release_key_raw(vk_code: int) -> None:
        """Release a held key."""
        _send_key_event(vk_code, True)

    def _system_wide_key_combo(key_names: list[str]) -> None:
        """Send a key combination at system level (e.g. Win+R, Ctrl+C).

        Uses Win32 keybd_event so the hotkey reaches the OS regardless
        of which window currently has keyboard focus.
        """
        vk_codes = [VK.get(k.lower()) for k in key_names]
        if any(v is None for v in vk_codes):
            raise ValueError(f"Unknown key in combo: {key_names} (resolved to {vk_codes})")

        # Press all modifier keys
        for vk in vk_codes[:-1]:
            _send_key_event(vk, False)
            time.sleep(0.02)
        # Press the action key
        _send_key_event(vk_codes[-1], False)
        time.sleep(0.05)
        # Release the action key
        _send_key_event(vk_codes[-1], True)
        # Release modifier keys in reverse
        for vk in reversed(vk_codes[:-1]):
            time.sleep(0.02)
            _send_key_event(vk, True)

    def _bring_window_to_front(title_fragment: str) -> bool:
        """Find a window by title fragment and bring it to the foreground."""
        import ctypes

        hwnd = ctypes.windll.user32.FindWindowW(None, None)
        # Enumerate all windows
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        GetWindowTextW = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLengthW = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        SetForegroundWindow = ctypes.windll.user32.SetForegroundWindow

        found_hwnd = ctypes.c_int(0)

        def enum_callback(hwnd_int, _):
            nonlocal found_hwnd
            hwnd = ctypes.c_int(hwnd_int)
            if not IsWindowVisible(hwnd):
                return True
            length = GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if title and title_fragment.lower() in title.lower():
                found_hwnd = hwnd
                return False  # Stop enumeration
            return True

        EnumWindows(EnumWindowsProc(enum_callback), 0)
        if found_hwnd.value != 0:
            ctypes.windll.user32.ShowWindow(found_hwnd, 9)  # SW_RESTORE
            time.sleep(0.1)
            SetForegroundWindow(found_hwnd)
            return True
        return False

else:
    # Non-Windows stubs (macOS/Linux not yet supported for this feature)
    def _send_key_event(vk_code, key_up=False): pass
    def _press_key_raw(vk_code): pass
    def _hold_key_raw(vk_code): pass
    def _release_key_raw(vk_code): pass

    def _system_wide_key_combo(key_names):
        raise RuntimeError("System-wide key combo only supported on Windows")

    def _bring_window_to_front(title_fragment):
        return False


# ──────────────────────────────────────────────
#  Core functions
# ──────────────────────────────────────────────

# Known browser executable names to try
_BROWSER_NAMES = [
    "brave", "chrome", "firefox", "msedge", "opera",
    "iexplore", "safari",
]


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


def _open_application(name_or_path: str) -> dict[str, Any]:
    """Open an application.

    Tries in order:
    1. os.startfile(name_or_path) — opens anything Windows knows about
    2. subprocess.Popen([name_or_path]) — run directly as command
    3. subprocess.Popen([name_or_path], shell=True) — via shell

    Returns result dict with success status.
    """
    logger.info("Opening application: %s", name_or_path)

    # Method 1: os.startfile (opens files, URLs, and registered apps)
    try:
        os.startfile(name_or_path)
        return {"success": True, "method": "startfile", "target": name_or_path}
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug("startfile failed for '%s': %s", name_or_path, e)

    # Method 2: Try as an executable command
    try:
        subprocess.Popen([name_or_path], shell=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True, "method": "popen", "target": name_or_path}
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug("Popen failed for '%s': %s", name_or_path, e)

    # Method 3: Try via shell (handles PATH-lookup)
    try:
        subprocess.Popen(name_or_path, shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True, "method": "shell", "target": name_or_path}
    except OSError as e:
        logger.debug("Shell popen failed for '%s': %s", name_or_path, e)

    return {"success": False, "error": f"Could not open '{name_or_path}'"}


def _open_browser(name: str = "brave") -> dict[str, Any]:
    """Open the first available browser.

    Args:
        name: Preferred browser name (default: brave)

    Returns result with which browser was opened.
    """
    attempts = [name] + [b for b in _BROWSER_NAMES if b != name]
    for browser in attempts:
        result = _open_application(browser)
        if result["success"]:
            result["browser"] = browser
            return result
    return {"success": False, "error": f"No browser found (tried: {', '.join(attempts)})"}


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
    """Type text character by character at the current keyboard cursor position."""
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.typewrite(text, interval=interval)
    return {"success": True, "action": "type", "text": text}


def _key_press(keys: str) -> dict[str, Any]:
    """Press a single key or key combination.

    Single keys use pyautogui (needs focus).
    System-wide combos (win+, ctrl+alt+del, etc.) use Win32 API.
    """
    import pyautogui

    pyautogui.FAILSAFE = True
    parts = [k.strip() for k in keys.split("+")]

    # For Win-key combos and multi-key system shortcuts,
    # use system-wide events so they work regardless of focus
    is_system_combo = (
        len(parts) > 1
        and any(k.lower() in ("win", "lwin", "rwin") for k in parts)
    )

    if is_system_combo and _is_windows:
        _system_wide_key_combo(parts)
    elif len(parts) == 1:
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


def _navigate_url_in_browser(url: str) -> dict[str, Any]:
    """Focus the browser address bar and type a URL, then press Enter.

    Assumes a browser is already open and visible.
    Uses Ctrl+L to focus address bar, then types the URL.
    """
    _wait(0.3)
    # Ctrl+L focuses the address bar in all major browsers
    _system_wide_key_combo(["ctrl", "l"])
    _wait(0.3)
    _type_text(url)
    _wait(0.2)
    _system_wide_key_combo(["enter"])
    return {"success": True, "url": url}


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
                        "description": "Monitor index to capture (0 = primary)",
                        "default": 0,
                    },
                },
            },
        ),
        Tool(
            name="get_screen_size",
            description="Get the primary screen width and height in pixels.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_display_info",
            description="Get information about all connected displays.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="get_mouse_position",
            description="Get the current mouse cursor (x, y) coordinates.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="mouse_move",
            description="Move the mouse cursor to the specified (x, y) coordinates smoothly.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "Horizontal pixel coordinate"},
                    "y": {"type": "integer", "description": "Vertical pixel coordinate"},
                    "duration": {"type": "number", "description": "Movement duration in seconds (default: 0.3)", "default": 0.3},
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
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "clicks": {"type": "integer", "enum": [1, 2, 3], "default": 1},
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
                    "interval": {"type": "number", "description": "Delay between keystrokes in seconds", "default": 0.02},
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="key_press",
            description="Press a single key or key combination. Uses system-level events for Win-key combos (win+r, win+d, etc.) so they work regardless of focus.",
            inputSchema={
                "type": "object",
                "properties": {
                    "keys": {"type": "string", "description": "Key or combination, e.g. 'enter', 'ctrl+c', 'win+r'"},
                },
                "required": ["keys"],
            },
        ),
        Tool(
            name="open_app",
            description="Open an application by name or path. Uses os.startfile which is reliable regardless of which window has focus. Examples: 'notepad', 'calc', 'brave', 'C:/Program Files/App/app.exe'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Application name or path to open"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="open_browser",
            description="Open a browser (brave/chrome/firefox/edge). Uses direct process launch so it works reliably regardless of focus.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Browser name: brave, chrome, firefox, msedge, opera", "default": "brave"},
                },
            },
        ),
        Tool(
            name="navigate_browser",
            description="Navigate the currently focused browser to a URL. Uses Ctrl+L to focus the address bar, then types the URL and presses Enter. Assumes a browser window is open and visible.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to navigate to, e.g. 'douyin.com' or 'https://github.com'"},
                },
                "required": ["url"],
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
                    "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
                    "amount": {"type": "integer", "description": "Number of scroll notches", "default": 3},
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="drag",
            description="Mouse drag from a start position to an end position.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_x": {"type": "integer"}, "start_y": {"type": "integer"},
                    "end_x": {"type": "integer"}, "end_y": {"type": "integer"},
                    "duration": {"type": "number", "default": 0.5},
                },
                "required": ["start_x", "start_y", "end_x", "end_y"],
            },
        ),
        Tool(
            name="wait",
            description="Pause execution for a specified duration. Max: 10.0s.",
            inputSchema={
                "type": "object",
                "properties": {
                    "duration": {"type": "number", "description": "Wait duration in seconds", "default": 1.0},
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
                TextContent(type="text", text=f"Screenshot captured: {result['width']}x{result['height']}"),
                ImageContent(type="image", data=result["data"], mimeType="image/png"),
            ]

        elif name == "get_screen_size":
            result = await asyncio.to_thread(_screen_size)
            return [TextContent(type="text", text=f"Screen: {result['width']} x {result['height']}")]

        elif name == "get_display_info":
            result = await asyncio.to_thread(_get_display_info)
            lines = [
                f"Display {d['index']}: {d['width']}x{d['height']}"
                f" at ({d['x']},{d['y']}){' [PRIMARY]' if d['is_primary'] else ''}"
                for d in result
            ]
            return [TextContent(type="text", text="Displays:\n" + "\n".join(lines))]

        elif name == "get_mouse_position":
            result = await asyncio.to_thread(_current_mouse_position)
            return [TextContent(type="text", text=f"Mouse: ({result['x']}, {result['y']})")]

        elif name == "mouse_move":
            await asyncio.to_thread(_mouse_move, arguments["x"], arguments["y"], arguments.get("duration", 0.3))
            return [TextContent(type="text", text=f"Moved mouse to ({arguments['x']}, {arguments['y']})")]

        elif name == "click":
            await asyncio.to_thread(
                _mouse_click,
                arguments["x"], arguments["y"],
                arguments.get("button", "left"),
                arguments.get("clicks", 1),
            )
            b = arguments.get("button", "left")
            c = arguments.get("clicks", 1)
            label = f"{'double-' if c == 2 else 'triple-' if c == 3 else ''}{b}-click"
            return [TextContent(type="text", text=f"{label} at ({arguments['x']}, {arguments['y']})")]

        elif name == "type_text":
            text = arguments["text"]
            await asyncio.to_thread(_type_text, text, arguments.get("interval", 0.02))
            return [TextContent(type="text", text=f"Typed {len(text)} characters")]

        elif name == "key_press":
            keys = arguments["keys"]
            await asyncio.to_thread(_key_press, keys)
            return [TextContent(type="text", text=f"Pressed: {keys}")]

        elif name == "open_app":
            result = await asyncio.to_thread(_open_application, arguments["name"])
            if result["success"]:
                return [TextContent(type="text", text=f"Opened '{arguments['name']}' via {result['method']}")]
            return [TextContent(type="text", text=f"Failed to open '{arguments['name']}': {result.get('error')}")]

        elif name == "open_browser":
            browser_name = arguments.get("name", "brave")
            result = await asyncio.to_thread(_open_browser, browser_name)
            if result["success"]:
                return [TextContent(type="text", text=f"Opened {result['browser']} browser via {result['method']}")]
            return [TextContent(type="text", text=result["error"])]

        elif name == "navigate_browser":
            result = await asyncio.to_thread(_navigate_url_in_browser, arguments["url"])
            return [TextContent(type="text", text=f"Navigating to: {result['url']}")]

        elif name == "scroll":
            await asyncio.to_thread(
                _scroll,
                arguments["x"], arguments["y"],
                arguments.get("direction", "down"),
                arguments.get("amount", 3),
            )
            return [TextContent(type="text", text=f"Scrolled {arguments.get('direction', 'down')} at ({arguments['x']}, {arguments['y']})")]

        elif name == "drag":
            await asyncio.to_thread(
                _drag,
                arguments["start_x"], arguments["start_y"],
                arguments["end_x"], arguments["end_y"],
                arguments.get("duration", 0.5),
            )
            return [TextContent(type="text", text=f"Dragged ({arguments['start_x']},{arguments['start_y']}) -> ({arguments['end_x']},{arguments['end_y']})")]

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
