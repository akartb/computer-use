"""
MCP Server for Computer Use Plugin — Claude Desktop integration.

Virtual cursor overlay + screenshot feedback loop.
Every action tool captures before/after screenshots so Claude can
visually verify the result and adjust if needed.

Usage — add to claude_desktop_config.json:
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
import subprocess
import sys
import threading
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent
from PIL import Image, ImageChops

logger = logging.getLogger("computer-use-mcp")


# ═══════════════════════════════════════════════════════════════
#  Virtual Cursor Overlay
# ═══════════════════════════════════════════════════════════════

class VirtualCursor:
    """Transparent overlay showing a red arrow cursor at the target position."""

    def __init__(self):
        self._root: Any = None
        self._canvas: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._x: float = 0
        self._y: float = 0
        self._tx: float = 0
        self._ty: float = 0
        self._label: str = ""
        self._sw: int = 1920
        self._sh: int = 1080
        self._cursor_items: list = []
        self._ripple_items: list = []
        self._label_id: Any = None
        self._status_id: Any = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        time.sleep(0.4)

    def stop(self):
        self._running = False
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def show_click(self, x, y, label=""):
        self._tx, self._ty = x, y
        self._label = label
        if self._root:
            self._root.after(5, lambda: self._draw_ripple(x, y, label))

    def show_type(self, text):
        if self._root:
            s = text[:40]
            self._root.after(5, lambda: self._show_label(f'Typing: "{s}"'))

    def show_scroll(self, direction, amount):
        a = "▲" if direction == "up" else "▼"
        if self._root:
            self._root.after(5, lambda: self._show_label(f"Scroll {a} x{amount}"))

    def show_drag(self, sx, sy, ex, ey):
        if self._root:
            self._root.after(5, lambda: self._draw_drag_line(sx, sy, ex, ey))

    def set_status(self, text):
        if self._root:
            self._root.after(5, lambda: self._draw_status(text))

    # ── internals ──────────────────────────

    def _run(self):
        import tkinter as tk
        self._root = tk.Tk()
        self._root.withdraw()
        self._sw = self._root.winfo_screenwidth()
        self._sh = self._root.winfo_screenheight()
        self._root = tk.Toplevel(self._root)
        self._root.title("ComputerUse-Cursor")
        self._root.attributes("-topmost", True)
        self._root.attributes("-transparentcolor", "#F0F0F0")
        self._root.overrideredirect(True)
        self._root.geometry(f"{self._sw}x{self._sh}+0+0")
        try:
            self._root.attributes("-alpha", 0.80)
        except Exception:
            pass
        self._canvas = tk.Canvas(self._root, width=self._sw, height=self._sh,
                                 bg="#F0F0F0", highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self._draw_cursor()
        self._root.after(50, self._animate)
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)
        self._root.mainloop()

    def _draw_cursor(self):
        x, y, s = self._x, self._y, 24
        self._cursor_items.append(
            self._canvas.create_polygon(
                x, y, x, y + s, x + s * 0.3, y + s * 0.7,
                x + s * 0.6, y + s * 1.2, x + s * 0.75, y + s * 1.0,
                x + s * 0.45, y + s * 0.6, x + s, y + s * 0.5,
                fill="#FF2222", outline="#FFFFFF", width=3,
            )
        )
        self._label_id = self._canvas.create_text(
            x + s + 8, y, text="", fill="#FFD700", font=("Consolas", 10, "bold"), anchor="w",
        )
        self._status_id = self._canvas.create_text(
            10, self._sh - 30, text="", fill="#00FF88", font=("Consolas", 11, "bold"), anchor="w",
        )
        self._draw_status("Computer Use Ready")

    def _animate(self):
        if not self._running:
            return
        dx = self._tx - self._x
        dy = self._ty - self._y
        if abs(dx) > 0.3 or abs(dy) > 0.3:
            self._x += dx * 0.35
            self._y += dy * 0.35
            for item in self._cursor_items:
                self._canvas.delete(item)
            self._cursor_items.clear()
            x, y, s = self._x, self._y, 24
            self._cursor_items.append(
                self._canvas.create_polygon(
                    x, y, x, y + s, x + s * 0.3, y + s * 0.7,
                    x + s * 0.6, y + s * 1.2, x + s * 0.75, y + s * 1.0,
                    x + s * 0.45, y + s * 0.6, x + s, y + s * 0.5,
                    fill="#FF2222", outline="#FFFFFF", width=3,
                )
            )
            if self._label_id:
                self._canvas.coords(self._label_id, x + s + 8, y)
        if self._running and self._root:
            self._root.after(16, self._animate)

    def _draw_ripple(self, x, y, label):
        self._show_label(label)
        for r in [8, 16, 24, 32]:
            item = self._canvas.create_oval(x - r, y - r, x + r, y + r, outline="#FF2222", width=3)
            self._ripple_items.append(item)
        self._root.after(400, self._clear_ripples)

    def _clear_ripples(self):
        for item in self._ripple_items:
            try:
                self._canvas.delete(item)
            except Exception:
                pass
        self._ripple_items.clear()

    def _draw_drag_line(self, sx, sy, ex, ey):
        self._show_label("Drag")
        self._canvas.create_line(sx, sy, ex, ey, fill="#FF8800", width=3, dash=(4, 4), tags="drag")
        self._canvas.create_oval(ex - 5, ey - 5, ex + 5, ey + 5, fill="#FF8800", tags="drag")
        self._root.after(800, lambda: self._canvas.delete("drag"))

    def _show_label(self, text):
        if self._label_id:
            self._canvas.itemconfig(self._label_id, text=text)
            self._root.after(1500, lambda: self._canvas.itemconfig(self._label_id, text=""))

    def _draw_status(self, text):
        if self._status_id:
            self._canvas.itemconfig(self._status_id, text=f"[AI] {text}")


# ═══════════════════════════════════════════════════════════════
#  Screenshot + Change Detection
# ═══════════════════════════════════════════════════════════════

_cursor: VirtualCursor | None = None


def _get_cursor() -> VirtualCursor:
    global _cursor
    if _cursor is None:
        _cursor = VirtualCursor()
        _cursor.start()
    return _cursor


def _capture_raw(monitor: int = 0) -> tuple[Image.Image, str]:
    """Capture screen, return (PIL Image, base64 string)."""
    import mss
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor >= len(monitors):
            monitor = 0
        raw = sct.grab(monitors[monitor])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return img, b64


def _compute_diff(before_img: Image.Image, after_img: Image.Image) -> float:
    """Return pixel change ratio between two images (0.0 = identical, 1.0 = totally different)."""
    if before_img.size != after_img.size:
        return 1.0
    diff = ImageChops.difference(before_img, after_img)
    bbox = diff.getbbox()
    if bbox is None:
        return 0.0
    try:
        diff_data = list(diff.get_flattened_data())
    except AttributeError:
        diff_data = list(diff.getdata())
    total = len(diff_data)
    if total == 0:
        return 0.0
    changed = sum(1 for r, g, b in diff_data if r > 12 or g > 12 or b > 12)
    return changed / total


def _action_with_feedback(action_fn, *args, **kwargs) -> dict:
    """
    Execute an action, then capture an after-screenshot and detect changes.

    Returns dict with:
      - success, action, description
      - after_screenshot (base64 PNG)
      - changed (bool): whether the screen visibly changed
      - change_ratio (float): percentage of pixels changed
    """
    before_img, before_b64 = _capture_raw(0)

    # Execute the action
    result = action_fn(*args, **kwargs)

    # Wait briefly for UI to respond, then capture after
    time.sleep(0.4)
    after_img, after_b64 = _capture_raw(0)

    ratio = _compute_diff(before_img, after_img)
    changed = ratio > 0.001  # more than 0.1% pixels changed

    return {
        **result,
        "after_screenshot": after_b64,
        "before_screenshot": before_b64,
        "changed": changed,
        "change_ratio": round(ratio * 100, 3),
    }


# ═══════════════════════════════════════════════════════════════
#  Core actions
# ═══════════════════════════════════════════════════════════════


def _capture_screen(monitor: int = 0) -> dict:
    _, b64 = _capture_raw(monitor)
    from PIL import Image as PILImage
    img = PILImage.open(io.BytesIO(base64.b64decode(b64)))
    w, h = img.size
    return {"data": b64, "width": w, "height": h, "monitor": monitor}


def _screen_size() -> dict:
    import pyautogui
    w, h = pyautogui.size()
    return {"width": w, "height": h}


def _get_display_info() -> list[dict]:
    import mss
    displays = []
    with mss.mss() as sct:
        for i, mon in enumerate(sct.monitors[1:], start=0):
            displays.append({
                "index": i, "width": mon["width"], "height": mon["height"],
                "x": mon["left"], "y": mon["top"], "is_primary": i == 0,
            })
    return displays


def _current_mouse_position() -> dict:
    import pyautogui
    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


def _mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict:
    import pyautogui
    pyautogui.FAILSAFE = True
    cursor = _get_cursor()
    labels = {1: "Click", 2: "Double-click"}
    cursor.show_click(x, y, f"{labels.get(clicks, 'Click')} ({button})")
    time.sleep(0.12)
    pyautogui.moveTo(x, y, duration=0.3)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    return {"success": True, "action": f"{button}_click", "x": x, "y": y, "clicks": clicks}


def _mouse_move(x: int, y: int, duration: float = 0.35) -> dict:
    import pyautogui
    pyautogui.FAILSAFE = True
    cursor = _get_cursor()
    cursor.show_click(x, y, "Move")
    pyautogui.moveTo(x, y, duration=duration)
    return {"success": True, "action": "move", "x": x, "y": y}


def _type_text(text: str, interval: float = 0.02,
               x: int | None = None, y: int | None = None,
               clicks: int = 1) -> dict:
    """Type text. If x,y given, clicks there first to establish focus.
    Uses clipboard+Ctrl+V for non-ASCII text (Chinese, emoji, etc.).
    """
    import pyautogui
    pyautogui.FAILSAFE = True
    cursor = _get_cursor()

    # Click first if coordinates given
    if x is not None and y is not None:
        cursor.show_click(x, y, "Click → Type")
        time.sleep(0.15)
        pyautogui.moveTo(x, y, duration=0.3)
        pyautogui.click(x=x, y=y, button="left", clicks=clicks)
        time.sleep(0.4)  # wait for focus to shift

    # Determine if we need clipboard mode (non-ASCII text)
    has_non_ascii = any(ord(c) > 127 for c in text)

    cursor.show_type(text)

    if has_non_ascii:
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)
    else:
        pyautogui.typewrite(text, interval=interval)

    return {"success": True, "action": "type", "text": text,
            "length": len(text), "used_clipboard": has_non_ascii}


def _key_press(keys: str) -> dict:
    import pyautogui
    pyautogui.FAILSAFE = True
    parts = [k.strip() for k in keys.split("+")]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return {"success": True, "action": "key_press", "keys": parts}


def _scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> dict:
    import pyautogui
    pyautogui.FAILSAFE = True
    cursor = _get_cursor()
    cursor.show_click(x, y, f"Scroll {direction}")
    time.sleep(0.1)
    pyautogui.moveTo(x, y, duration=0.2)
    delta = amount if direction == "down" else -amount
    pyautogui.scroll(delta, x=x, y=y)
    cursor.show_scroll(direction, amount)
    return {"success": True, "action": "scroll", "x": x, "y": y,
            "direction": direction, "amount": amount}


def _drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> dict:
    import pyautogui
    pyautogui.FAILSAFE = True
    cursor = _get_cursor()
    cursor.show_drag(start_x, start_y, end_x, end_y)
    time.sleep(0.1)
    pyautogui.moveTo(start_x, start_y, duration=0.3)
    pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
    return {"success": True, "action": "drag",
            "start_x": start_x, "start_y": start_y,
            "end_x": end_x, "end_y": end_y}


def _wait(duration: float = 1.0) -> dict:
    time.sleep(duration)
    return {"success": True, "action": "wait", "duration": duration}


def _open_app(name: str) -> dict:
    """Open an application by name via subprocess (most reliable method).
    This bypasses keyboard focus issues entirely."""
    # Common app launch commands
    if name.lower() in ("edge", "microsoft edge"):
        cmd = "start microsoft-edge:"
    elif name.lower() in ("brave",):
        cmd = "start brave"
    elif name.lower() in ("chrome", "google chrome"):
        cmd = "start chrome"
    elif name.lower() in ("firefox",):
        cmd = "start firefox"
    elif name.lower() in ("notepad",):
        cmd = "start notepad"
    elif name.lower() in ("calc", "calculator"):
        cmd = "start calc"
    else:
        cmd = f"start {name}"

    try:
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True, "action": "open_app", "app": name}
    except Exception as e:
        return {"success": False, "action": "open_app", "app": name, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  MCP Server
# ═══════════════════════════════════════════════════════════════

app = Server("computer-use")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="screenshot", description="Capture the current screen. Returns a base64-encoded PNG image so you can see what's on screen. Use this to observe the current state before deciding what to do.",
             inputSchema={"type": "object", "properties": {"monitor": {"type": "integer", "default": 0}}}),

        Tool(name="get_screen_size", description="Get screen dimensions (width x height) in pixels.",
             inputSchema={"type": "object", "properties": {}, "required": []}),
        Tool(name="get_display_info", description="Get information about all connected displays.",
             inputSchema={"type": "object", "properties": {}, "required": []}),
        Tool(name="get_mouse_position", description="Get current mouse cursor coordinates.",
             inputSchema={"type": "object", "properties": {}, "required": []}),

        Tool(name="mouse_move", description="Move the mouse smoothly to (x,y). The virtual cursor shows the movement.",
             inputSchema={"type": "object", "properties": {
                 "x": {"type": "integer"}, "y": {"type": "integer"},
                 "duration": {"type": "number", "default": 0.35},
             }, "required": ["x", "y"]}),

        Tool(name="click", description="""Click at (x,y). A red virtual cursor appears at the click position with a ripple effect.
After clicking, the tool CAPTURES A NEW SCREENSHOT and checks if the click had any visual effect.
Returns: 'changed' (true/false), 'change_ratio' (%), and the new screenshot.
If changed=false, the click missed — adjust coordinates and retry.""",
             inputSchema={"type": "object", "properties": {
                 "x": {"type": "integer", "description": "Horizontal pixel coordinate"}, "y": {"type": "integer"},
                 "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                 "clicks": {"type": "integer", "enum": [1, 2], "default": 1},
             }, "required": ["x", "y"]}),

        Tool(name="type_text", description="""Type text. Uses clipboard+Ctrl+V for Chinese/emoji automatically.
IMPORTANT: Provide (x,y) to CLICK ON the target input field FIRST — this ensures the text goes to the right window.
After typing, captures a new screenshot and reports whether the screen changed.
Example: type_text(text='你好世界', x=500, y=60) — clicks address bar then types.""",
             inputSchema={"type": "object", "properties": {
                 "text": {"type": "string", "description": "Text to type (Chinese/emoji OK)"},
                 "x": {"type": "integer", "description": "Click X before typing (to focus the target field)"},
                 "y": {"type": "integer", "description": "Click Y before typing"},
                 "clicks": {"type": "integer", "enum": [1, 2], "default": 1},
                 "interval": {"type": "number", "default": 0.02},
             }, "required": ["text"]}),

        Tool(name="key_press", description="Press a key or combo (e.g. 'enter', 'ctrl+v'). Captures after-screenshot.",
             inputSchema={"type": "object", "properties": {
                 "keys": {"type": "string", "description": "Key or combo like 'enter', 'ctrl+v', 'alt+tab'"},
             }, "required": ["keys"]}),

        Tool(name="scroll", description="Scroll at (x,y). Shows virtual cursor, captures after-screenshot with change detection.",
             inputSchema={"type": "object", "properties": {
                 "x": {"type": "integer"}, "y": {"type": "integer"},
                 "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
                 "amount": {"type": "integer", "default": 3},
             }, "required": ["x", "y"]}),

        Tool(name="drag", description="Drag from (start_x,start_y) to (end_x,end_y). Shows a visual line. Captures after-screenshot.",
             inputSchema={"type": "object", "properties": {
                 "start_x": {"type": "integer"}, "start_y": {"type": "integer"},
                 "end_x": {"type": "integer"}, "end_y": {"type": "integer"},
                 "duration": {"type": "number", "default": 0.5},
             }, "required": ["start_x", "start_y", "end_x", "end_y"]}),

        Tool(name="wait", description="Pause for a duration. Use between actions.",
             inputSchema={"type": "object", "properties": {"duration": {"type": "number", "default": 1.0}}}),

        Tool(name="open_app", description="""Open an application by name. Uses direct process launch (most reliable, no keyboard simulation needed).
Supported names: edge, brave, chrome, firefox, notepad, calc, settings.""",
             inputSchema={"type": "object", "properties": {
                 "name": {"type": "string", "description": "App name: edge, brave, chrome, firefox, notepad, calc, settings"},
             }, "required": ["name"]}),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    try:
        # ─── Read-only tools ───────────────────────

        if name == "screenshot":
            r = await asyncio.to_thread(_capture_screen, arguments.get("monitor", 0))
            status = _get_cursor()
            status.set_status("Screenshot captured")
            return [
                TextContent(type="text", text=f"Screen: {r['width']}x{r['height']} (monitor {r['monitor']})\nLook at this screenshot and decide the next action. Estimate pixel coordinates of what you want to click."),
                ImageContent(type="image", data=r["data"], mimeType="image/png"),
            ]

        elif name == "get_screen_size":
            r = await asyncio.to_thread(_screen_size)
            return [TextContent(type="text", text=f"{r['width']} x {r['height']}")]

        elif name == "get_display_info":
            r = await asyncio.to_thread(_get_display_info)
            lines = [f"Disp {d['index']}: {d['width']}x{d['height']} at ({d['x']},{d['y']}){' [PRIMARY]' if d['is_primary'] else ''}" for d in r]
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_mouse_position":
            r = await asyncio.to_thread(_current_mouse_position)
            return [TextContent(type="text", text=f"({r['x']}, {r['y']})")]

        # ─── Actions with screenshot feedback ──────

        elif name == "mouse_move":
            r = await asyncio.to_thread(_action_with_feedback, _mouse_move,
                                        arguments["x"], arguments["y"],
                                        arguments.get("duration", 0.35))
            c = r["changed"]
            return [
                TextContent(type="text", text=f"Mouse moved to ({arguments['x']},{arguments['y']}). Screen changed: {c} ({r['change_ratio']}%)"),
                ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png"),
            ]

        elif name == "click":
            r = await asyncio.to_thread(_action_with_feedback, _mouse_click,
                                        arguments["x"], arguments["y"],
                                        arguments.get("button", "left"),
                                        arguments.get("clicks", 1))
            b = arguments.get("button", "left")
            c = arguments.get("clicks", 1)
            label = f"{'Double-' if c == 2 else ''}{b}-click"
            ch = "YES" if r["changed"] else "NO"
            hint = "" if r["changed"] else "\nNo visual change detected — the click may have missed the target. Try adjusting coordinates slightly."
            return [
                TextContent(type="text", text=f"{label} at ({arguments['x']},{arguments['y']}). Changed: {ch} ({r['change_ratio']}% pixels){hint}"),
                ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png"),
            ]

        elif name == "type_text":
            text = arguments["text"]
            cx = arguments.get("x")
            cy = arguments.get("y")
            cl = arguments.get("clicks", 1)
            r = await asyncio.to_thread(_action_with_feedback, _type_text,
                                        text, arguments.get("interval", 0.02), cx, cy, cl)
            ch = "YES" if r["changed"] else "NO"
            clip = " (via clipboard)" if r.get("used_clipboard", False) else ""
            ctx = f" (clicked ({cx},{cy}) first)" if cx is not None else ""
            return [
                TextContent(type="text", text=f"Typed {len(text)} chars{clip}{ctx}. Changed: {ch} ({r['change_ratio']}%)"),
                ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png"),
            ]

        elif name == "key_press":
            r = await asyncio.to_thread(_action_with_feedback, _key_press, arguments["keys"])
            ch = "YES" if r["changed"] else "NO"
            return [
                TextContent(type="text", text=f"Pressed {arguments['keys']}. Changed: {ch} ({r['change_ratio']}%)"),
                ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png"),
            ]

        elif name == "scroll":
            r = await asyncio.to_thread(_action_with_feedback, _scroll,
                                        arguments["x"], arguments["y"],
                                        arguments.get("direction", "down"),
                                        arguments.get("amount", 3))
            ch = "YES" if r["changed"] else "NO"
            return [
                TextContent(type="text", text=f"Scrolled {arguments.get('direction','down')} at ({arguments['x']},{arguments['y']}). Changed: {ch} ({r['change_ratio']}%)"),
                ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png"),
            ]

        elif name == "drag":
            r = await asyncio.to_thread(_action_with_feedback, _drag,
                                        arguments["start_x"], arguments["start_y"],
                                        arguments["end_x"], arguments["end_y"],
                                        arguments.get("duration", 0.5))
            ch = "YES" if r["changed"] else "NO"
            return [
                TextContent(type="text", text=f"Dragged ({arguments['start_x']},{arguments['start_y']})→({arguments['end_x']},{arguments['end_y']}). Changed: {ch}"),
                ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png"),
            ]

        elif name == "wait":
            d = min(arguments.get("duration", 1.0), 10.0)
            await asyncio.to_thread(_wait, d)
            return [TextContent(type="text", text=f"Waited {d}s")]

        # ─── App launcher ─────────────────────────

        elif name == "open_app":
            r = await asyncio.to_thread(_open_app, arguments["name"])
            if r["success"]:
                _wait(2.0)  # wait for app to open
                ss = _capture_screen(0)
                _get_cursor().set_status(f"Opened {arguments['name']}")
                return [
                    TextContent(type="text", text=f"Opened '{arguments['name']}'. Here's the current screen:"),
                    ImageContent(type="image", data=ss["data"], mimeType="image/png"),
                ]
            return [TextContent(type="text", text=f"Failed to open '{arguments['name']}': {r.get('error', 'unknown')}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run():
    logging.basicConfig(level=logging.WARNING)
    # Start the virtual cursor
    _get_cursor()
    asyncio.run(main())


if __name__ == "__main__":
    run()
