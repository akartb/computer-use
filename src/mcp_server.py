"""
MCP Server for Computer Use Plugin — integrates with Claude Desktop.

Exposes computer control tools with a virtual cursor overlay that shows
the AI's mouse movements and actions in real-time.

The AI observes the screen via screenshots, reasons about what to do,
and executes actions (click, type, scroll, drag, wait). A transparent
virtual cursor overlay provides visual feedback for every action.

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
import threading
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent

logger = logging.getLogger("computer-use-mcp")


# ══════════════════════════════════════════════
#  Virtual Cursor Overlay (tkinter, transparent)
# ══════════════════════════════════════════════

class VirtualCursor:
    """Lightweight virtual cursor overlay — shows AI's mouse on screen."""

    def __init__(self) -> None:
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
        self._anim_id: Any = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # Wait for tkinter to initialise
        time.sleep(0.3)

    def stop(self) -> None:
        self._running = False
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass

    def show_click(self, x: float, y: float, label: str = "") -> None:
        self._tx, self._ty = x, y
        self._label = label
        if self._root:
            self._root.after(5, lambda: self._draw_ripple(x, y, label))

    def show_type(self, text: str) -> None:
        if self._root:
            self._root.after(5, lambda: self._show_label(f'Typing: "{text[:30]}"'))

    def show_scroll(self, direction: str, amount: int) -> None:
        a = "▲" if direction == "up" else "▼"
        if self._root:
            self._root.after(5, lambda: self._show_label(f"Scroll {a} x{amount}"))

    def show_drag(self, sx: float, sy: float, ex: float, ey: float) -> None:
        if self._root:
            self._root.after(5, lambda: self._draw_drag_line(sx, sy, ex, ey))

    def set_status(self, text: str) -> None:
        if self._root:
            self._root.after(5, lambda: self._draw_status(text))

    # ── internals ────────────────────────────

    def _run(self) -> None:
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
            self._root.attributes("-alpha", 0.85)
        except Exception:
            pass
        self._canvas = tk.Canvas(self._root, width=self._sw, height=self._sh,
                                 bg="#F0F0F0", highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self._draw_cursor()
        self._draw_status("Computer Use ready")
        self._root.after(50, self._animate)
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)
        self._root.mainloop()

    def _draw_cursor(self) -> None:
        x, y, s = self._x, self._y, 20
        self._cursor_items.append(
            self._canvas.create_polygon(
                x, y, x, y + s, x + s * 0.3, y + s * 0.7,
                x + s * 0.6, y + s * 1.1, x + s * 0.75, y + s * 1.0,
                x + s * 0.45, y + s * 0.6, x + s, y + s * 0.6,
                fill="#FF4444", outline="#FFFFFF", width=2,
            )
        )
        self._label_id = self._canvas.create_text(
            x + s + 5, y, text="", fill="#FFD700", font=("Consolas", 10), anchor="w",
        )
        self._status_id = self._canvas.create_text(
            10, self._sh - 30, text="", fill="#00FF88", font=("Consolas", 11), anchor="w",
        )

    def _animate(self) -> None:
        if not self._running:
            return
        dx = self._tx - self._x
        dy = self._ty - self._y
        if abs(dx) > 0.5 or abs(dy) > 0.5:
            self._x += dx * 0.30
            self._y += dy * 0.30
            for item in self._cursor_items:
                self._canvas.delete(item)
            self._cursor_items.clear()
            x, y, s = self._x, self._y, 20
            self._cursor_items.append(
                self._canvas.create_polygon(
                    x, y, x, y + s, x + s * 0.3, y + s * 0.7,
                    x + s * 0.6, y + s * 1.1, x + s * 0.75, y + s * 1.0,
                    x + s * 0.45, y + s * 0.6, x + s, y + s * 0.6,
                    fill="#FF4444", outline="#FFFFFF", width=2,
                )
            )
            if self._label_id:
                self._canvas.coords(self._label_id, x + s + 5, y)
        self._anim_id = self._root.after(16, self._animate)

    def _draw_ripple(self, x: float, y: float, label: str) -> None:
        self._show_label(label)
        for r in [6, 12, 18, 24]:
            item = self._canvas.create_oval(x - r, y - r, x + r, y + r, outline="#FF4444", width=2)
            self._ripple_items.append(item)
        self._root.after(350, self._clear_ripples)

    def _clear_ripples(self) -> None:
        for item in self._ripple_items:
            try:
                self._canvas.delete(item)
            except Exception:
                pass
        self._ripple_items.clear()

    def _draw_drag_line(self, sx: float, sy: float, ex: float, ey: float) -> None:
        self._show_label("Drag")
        self._canvas.create_line(sx, sy, ex, ey, fill="#FF8800", width=3, dash=(4, 3), tags="drag")
        self._canvas.create_oval(ex - 4, ey - 4, ex + 4, ey + 4, fill="#FF8800", tags="drag")
        self._root.after(800, lambda: self._canvas.delete("drag"))

    def _show_label(self, text: str) -> None:
        if self._label_id:
            self._canvas.itemconfig(self._label_id, text=text)
            self._root.after(1200, lambda: self._canvas.itemconfig(self._label_id, text=""))

    def _draw_status(self, text: str) -> None:
        if self._status_id:
            self._canvas.itemconfig(self._status_id, text=f"[AI] {text}")


# ══════════════════════════════════════════════
#  Core functions (runs in threads)
# ══════════════════════════════════════════════

_cursor: VirtualCursor | None = None


def _get_cursor() -> VirtualCursor:
    global _cursor
    if _cursor is None:
        _cursor = VirtualCursor()
        _cursor.start()
    return _cursor


def _capture_screen(monitor: int = 0) -> dict[str, Any]:
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
    import mss
    displays: list[dict[str, Any]] = []
    with mss.mss() as sct:
        for i, mon in enumerate(sct.monitors[1:], start=0):
            displays.append({
                "index": i, "width": mon["width"], "height": mon["height"],
                "x": mon["left"], "y": mon["top"], "is_primary": i == 0,
            })
    return displays


def _mouse_click(x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, Any]:
    import pyautogui
    pyautogui.FAILSAFE = True

    cursor = _get_cursor()
    cursor.show_click(x, y, f"{'Double' if clicks == 2 else ''}{button.title()} Click")
    # Small delay so the user can see the virtual cursor
    time.sleep(0.15)

    pyautogui.moveTo(x, y, duration=0.35)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    return {"success": True, "action": "click", "x": x, "y": y, "button": button, "clicks": clicks}


def _mouse_move(x: int, y: int, duration: float = 0.35) -> dict[str, Any]:
    import pyautogui
    pyautogui.FAILSAFE = True

    cursor = _get_cursor()
    cursor.show_click(x, y, "Move")

    pyautogui.moveTo(x, y, duration=duration)
    return {"success": True, "action": "move", "x": x, "y": y}


def _type_text(text: str, interval: float = 0.02,
               x: int | None = None, y: int | None = None,
               clicks: int = 1) -> dict[str, Any]:
    """Type text. If (x, y) is provided, clicks there first to establish focus,
    then types. This ensures text goes to the correct field, not Claude Desktop.

    Use the x,y parameters to click on the target input field before typing.
    Without x,y, the text goes to whatever window currently has keyboard focus.
    """
    import pyautogui
    pyautogui.FAILSAFE = True

    cursor = _get_cursor()

    # Click first to set focus if coordinates provided
    if x is not None and y is not None:
        cursor.show_click(x, y, f"Click then type")
        time.sleep(0.15)
        pyautogui.moveTo(x, y, duration=0.35)
        pyautogui.click(x=x, y=y, button="left", clicks=clicks)
        # Wait for UI to register the click and shift focus
        time.sleep(0.3)

    cursor.show_type(text)
    time.sleep(0.1)

    pyautogui.typewrite(text, interval=interval)
    return {"success": True, "action": "type", "text": text,
            "clicked_before": (x is not None)}


def _key_press(keys: str) -> dict[str, Any]:
    """Press a key like 'enter', 'tab', 'escape', or combo like 'ctrl+a'.
    NOTE: For key combos to work on the right window, click on that window first."""
    import pyautogui
    pyautogui.FAILSAFE = True

    parts = [k.strip() for k in keys.split("+")]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return {"success": True, "action": "key_press", "keys": parts}


def _scroll(x: int, y: int, direction: str = "down", amount: int = 3) -> dict[str, Any]:
    import pyautogui
    pyautogui.FAILSAFE = True

    cursor = _get_cursor()
    cursor.show_click(x, y, "Scroll")
    time.sleep(0.1)

    pyautogui.moveTo(x, y, duration=0.25)
    scroll_amount = amount if direction == "down" else -amount
    pyautogui.scroll(scroll_amount, x=x, y=y)
    cursor.show_scroll(direction, amount)
    return {"success": True, "action": "scroll", "x": x, "y": y, "direction": direction, "amount": amount}


def _drag(start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> dict[str, Any]:
    import pyautogui
    pyautogui.FAILSAFE = True

    cursor = _get_cursor()
    cursor.show_drag(start_x, start_y, end_x, end_y)
    time.sleep(0.1)

    pyautogui.moveTo(start_x, start_y, duration=0.3)
    pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
    return {"success": True, "action": "drag", "start_x": start_x, "start_y": start_y, "end_x": end_x, "end_y": end_y}


def _wait(duration: float = 1.0) -> dict[str, Any]:
    time.sleep(duration)
    return {"success": True, "action": "wait", "duration": duration}


def _current_mouse_position() -> dict[str, Any]:
    import pyautogui
    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


def _screen_size() -> dict[str, Any]:
    import pyautogui
    w, h = pyautogui.size()
    return {"width": w, "height": h}


# ══════════════════════════════════════════════
#  MCP Server
# ══════════════════════════════════════════════

app = Server("computer-use")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="screenshot", description="Capture the current screen. Returns a base64-encoded PNG image so you can see what's on screen and decide the next action.",
             inputSchema={"type": "object", "properties": {
                 "monitor": {"type": "integer", "description": "Monitor index (0 = primary)", "default": 0},
             }}),
        Tool(name="get_screen_size", description="Get the primary screen dimensions (width x height) in pixels.",
             inputSchema={"type": "object", "properties": {}, "required": []}),
        Tool(name="get_display_info", description="Get information about all connected displays.",
             inputSchema={"type": "object", "properties": {}, "required": []}),
        Tool(name="get_mouse_position", description="Get current mouse cursor (x, y) coordinates.",
             inputSchema={"type": "object", "properties": {}, "required": []}),
        Tool(name="mouse_move", description="Move the mouse cursor smoothly to (x, y). A virtual cursor overlay shows the movement.",
             inputSchema={"type": "object", "properties": {
                 "x": {"type": "integer", "description": "Horizontal pixel coordinate (0 = left edge)"},
                 "y": {"type": "integer", "description": "Vertical pixel coordinate (0 = top edge)"},
                 "duration": {"type": "number", "description": "Movement duration in seconds", "default": 0.35},
             }, "required": ["x", "y"]}),
        Tool(name="click", description="""Click the mouse at (x, y). A red virtual cursor shows where the click happens with a ripple effect.
Use this tool FIRST before typing — clicking on a text field gives it keyboard focus so typing goes to the right place.
Supports left/right/middle button and single/double clicks.""",
             inputSchema={"type": "object", "properties": {
                 "x": {"type": "integer", "description": "Horizontal pixel coordinate"},
                 "y": {"type": "integer", "description": "Vertical pixel coordinate"},
                 "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                 "clicks": {"type": "integer", "enum": [1, 2], "default": 1,
                            "description": "1=single, 2=double (double-click selects all text in input fields)"},
             }, "required": ["x", "y"]}),
        Tool(name="type_text", description="""Type text. CRITICAL: Provide x,y to click on the target input field FIRST before typing. This ensures the text goes to the right window (not Claude Desktop).
If x,y are omitted, text goes to the currently focused window.
Use double_click (clicks=2) to select all existing text before typing.""",
             inputSchema={"type": "object", "properties": {
                 "text": {"type": "string", "description": "The text to type"},
                 "x": {"type": "integer", "description": "Click at this X coordinate BEFORE typing (to set focus on target input field)"},
                 "y": {"type": "integer", "description": "Click at this Y coordinate BEFORE typing"},
                 "clicks": {"type": "integer", "enum": [1, 2], "default": 1, "description": "1=click once, 2=double-click (selects all existing text)"},
                 "interval": {"type": "number", "description": "Delay between keystrokes in seconds", "default": 0.02},
             }, "required": ["text"]}),
        Tool(name="key_press", description="""Press a single key or key combination. Use AFTER clicking on the target window.
Single keys: 'enter', 'tab', 'escape', 'backspace', 'space', arrow keys.
Combos: 'ctrl+a', 'ctrl+v', etc. Use '+' to separate keys.""",
             inputSchema={"type": "object", "properties": {
                 "keys": {"type": "string", "description": "Key or combo, e.g. 'enter', 'ctrl+c', 'ctrl+v'"},
             }, "required": ["keys"]}),
        Tool(name="scroll", description="Scroll the mouse wheel at (x, y). Virtual cursor shows the scroll direction and amount.",
             inputSchema={"type": "object", "properties": {
                 "x": {"type": "integer"}, "y": {"type": "integer"},
                 "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
                 "amount": {"type": "integer", "description": "Number of scroll notches", "default": 3},
             }, "required": ["x", "y"]}),
        Tool(name="drag", description="Drag mouse from (start_x, start_y) to (end_x, end_y). Shows a visual drag line.",
             inputSchema={"type": "object", "properties": {
                 "start_x": {"type": "integer"}, "start_y": {"type": "integer"},
                 "end_x": {"type": "integer"}, "end_y": {"type": "integer"},
                 "duration": {"type": "number", "default": 0.5},
             }, "required": ["start_x", "start_y", "end_x", "end_y"]}),
        Tool(name="wait", description="Pause execution. Use between actions to wait for UI responses.", inputSchema={
            "type": "object", "properties": {"duration": {"type": "number", "default": 1.0}}}),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    try:
        if name == "screenshot":
            r = await asyncio.to_thread(_capture_screen, arguments.get("monitor", 0))
            return [
                TextContent(type="text", text=f"Screenshot captured: {r['width']}x{r['height']} (monitor {r['monitor']})\n\nAnalyze this screenshot and decide the next action. If you need to click on something, estimate its (x, y) coordinates from the image. Then use the click tool at those coordinates. If you need to type, click on the input field first, then use type_text."),
                ImageContent(type="image", data=r["data"], mimeType="image/png"),
            ]

        elif name == "get_screen_size":
            r = await asyncio.to_thread(_screen_size)
            return [TextContent(type="text", text=f"Screen size: {r['width']} x {r['height']} pixels")]

        elif name == "get_display_info":
            r = await asyncio.to_thread(_get_display_info)
            lines = [f"Display {d['index']}: {d['width']}x{d['height']} at ({d['x']},{d['y']}){' [PRIMARY]' if d['is_primary'] else ''}" for d in r]
            return [TextContent(type="text", text="Displays:\n" + "\n".join(lines))]

        elif name == "get_mouse_position":
            r = await asyncio.to_thread(_current_mouse_position)
            return [TextContent(type="text", text=f"Mouse position: ({r['x']}, {r['y']})")]

        elif name == "mouse_move":
            await asyncio.to_thread(_mouse_move, arguments["x"], arguments["y"], arguments.get("duration", 0.35))
            return [TextContent(type="text", text=f"Mouse moved to ({arguments['x']}, {arguments['y']})")]

        elif name == "click":
            await asyncio.to_thread(_mouse_click, arguments["x"], arguments["y"],
                                     arguments.get("button", "left"), arguments.get("clicks", 1))
            b, c = arguments.get("button", "left"), arguments.get("clicks", 1)
            label = f"{'Double-' if c == 2 else ''}{b}-click"
            return [TextContent(type="text", text=f"{label} at ({arguments['x']}, {arguments['y']}). Red cursor ripple should have appeared at this position.")]

        elif name == "type_text":
            text = arguments["text"]
            cx = arguments.get("x")
            cy = arguments.get("y")
            cl = arguments.get("clicks", 1)
            await asyncio.to_thread(_type_text, text, arguments.get("interval", 0.02), cx, cy, cl)
            msg = f"Typed {len(text)} characters: '{text[:40]}{'...' if len(text) > 40 else ''}'"
            if cx is not None:
                msg += f" (clicked at ({cx},{cy}) first)"
            return [TextContent(type="text", text=msg)]

        elif name == "key_press":
            await asyncio.to_thread(_key_press, arguments["keys"])
            return [TextContent(type="text", text=f"Pressed: {arguments['keys']}")]

        elif name == "scroll":
            await asyncio.to_thread(_scroll, arguments["x"], arguments["y"],
                                     arguments.get("direction", "down"), arguments.get("amount", 3))
            return [TextContent(type="text", text=f"Scrolled {arguments.get('direction','down')} x{arguments.get('amount',3)} at ({arguments['x']},{arguments['y']})")]

        elif name == "drag":
            await asyncio.to_thread(_drag, arguments["start_x"], arguments["start_y"],
                                     arguments["end_x"], arguments["end_y"], arguments.get("duration", 0.5))
            return [TextContent(type="text", text=f"Dragged ({arguments['start_x']},{arguments['start_y']}) -> ({arguments['end_x']},{arguments['end_y']})")]

        elif name == "wait":
            d = min(arguments.get("duration", 1.0), 10.0)
            await asyncio.to_thread(_wait, d)
            return [TextContent(type="text", text=f"Waited {d}s")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
        return [TextContent(type="text", text=f"Error: {e}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def run() -> None:
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())


if __name__ == "__main__":
    run()
