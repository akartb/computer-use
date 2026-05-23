"""
MCP Server for Computer Use Plugin — Claude Desktop integration.

Provides computer control tools via the Model Context Protocol.
Every actionable tool takes (x,y) coordinates for pixel-perfect targeting.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import subprocess
import threading
import time
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent
from PIL import Image, ImageChops

logger = logging.getLogger("computer-use-mcp")


# ════════════════════════════════════════
#  Virtual Cursor
# ════════════════════════════════════════

class VirtualCursor:
    """Transparent overlay showing a red arrow at the AI's target position."""

    def __init__(self):
        self._root: Any = None; self._canvas: Any = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._x: float = 0; self._y: float = 0
        self._tx: float = 0; self._ty: float = 0
        self._sw: int = 1920; self._sh: int = 1080
        self._cursor_items: list = []; self._ripple_items: list = []
        self._label_id: Any = None; self._status_id: Any = None

    def start(self):
        if self._running: return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        time.sleep(0.4)

    def stop(self):
        self._running = False
        if self._root:
            try: self._root.after(0, self._root.destroy)
            except Exception: pass

    def show_click(self, x, y, label=""):
        self._tx, self._ty = x, y
        if self._root: self._root.after(5, lambda: self._draw_ripple(x, y, label))

    def show_type(self, text):
        if self._root: self._root.after(5, lambda: self._show_label(f'Typing: "{text[:40]}"'))

    def set_status(self, text):
        if self._root: self._root.after(5, lambda: self._draw_status(text))

    def _run(self):
        import tkinter as tk
        self._root = tk.Tk(); self._root.withdraw()
        self._sw = self._root.winfo_screenwidth()
        self._sh = self._root.winfo_screenheight()
        self._root = tk.Toplevel(self._root)
        self._root.title("ComputerUse-Cursor")
        self._root.attributes("-topmost", True)
        self._root.attributes("-transparentcolor", "#F0F0F0")
        self._root.overrideredirect(True)
        self._root.geometry(f"{self._sw}x{self._sh}+0+0")
        try: self._root.attributes("-alpha", 0.80)
        except Exception: pass
        self._canvas = tk.Canvas(self._root, width=self._sw, height=self._sh,
                                 bg="#F0F0F0", highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self._draw_cursor()
        self._root.after(50, self._animate)
        self._root.protocol("WM_DELETE_WINDOW", lambda: None)
        self._root.mainloop()

    def _draw_cursor(self):
        x, y, s = self._x, self._y, 24
        self._cursor_items.append(self._canvas.create_polygon(
            x, y, x, y+s, x+s*0.3, y+s*0.7, x+s*0.6, y+s*1.2, x+s*0.75, y+s,
            x+s*0.45, y+s*0.6, x+s, y+s*0.5, fill="#FF2222", outline="#FFF", width=3))
        self._label_id = self._canvas.create_text(x+s+8, y, text="", fill="#FFD700",
                                                    font=("Consolas", 10, "bold"), anchor="w")
        self._status_id = self._canvas.create_text(10, self._sh-30, text="",
                                                    fill="#00FF88", font=("Consolas", 11, "bold"), anchor="w")

    def _animate(self):
        if not self._running: return
        dx, dy = self._tx - self._x, self._ty - self._y
        if abs(dx) > 0.3 or abs(dy) > 0.3:
            self._x += dx * 0.35; self._y += dy * 0.35
            for i in self._cursor_items: self._canvas.delete(i)
            self._cursor_items.clear()
            x, y, s = self._x, self._y, 24
            self._cursor_items.append(self._canvas.create_polygon(
                x, y, x, y+s, x+s*0.3, y+s*0.7, x+s*0.6, y+s*1.2, x+s*0.75, y+s,
                x+s*0.45, y+s*0.6, x+s, y+s*0.5, fill="#FF2222", outline="#FFF", width=3))
            if self._label_id: self._canvas.coords(self._label_id, x+s+8, y)
        if self._running and self._root: self._root.after(16, self._animate)

    def _draw_ripple(self, x, y, label):
        self._show_label(label)
        for r in [8, 16, 24, 32]:
            self._ripple_items.append(self._canvas.create_oval(x-r, y-r, x+r, y+r, outline="#FF2222", width=3))
        self._root.after(400, self._clear_ripples)

    def _clear_ripples(self):
        for i in self._ripple_items:
            try: self._canvas.delete(i)
            except Exception: pass
        self._ripple_items.clear()

    def _show_label(self, text):
        if self._label_id:
            self._canvas.itemconfig(self._label_id, text=text)
            self._root.after(1500, lambda: self._canvas.itemconfig(self._label_id, text=""))

    def _draw_status(self, text):
        if self._status_id: self._canvas.itemconfig(self._status_id, text=f"[AI] {text}")


# ════════════════════════════════════════
#  Screenshot + Diff
# ════════════════════════════════════════

_cursor: VirtualCursor | None = None

def _get_cursor():
    global _cursor
    if _cursor is None: _cursor = VirtualCursor(); _cursor.start()
    return _cursor

def _capture_raw(monitor=0):
    import mss
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor >= len(mons): monitor = 0
        raw = sct.grab(mons[monitor])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        buf = io.BytesIO(); img.save(buf, format="PNG")
        return img, base64.b64encode(buf.getvalue()).decode("utf-8")

def _compute_diff(before, after):
    if before.size != after.size: return 1.0
    diff = ImageChops.difference(before, after)
    if diff.getbbox() is None: return 0.0
    try: data = list(diff.get_flattened_data())
    except AttributeError: data = list(diff.getdata())
    total = len(data)
    if total == 0: return 0.0
    return sum(1 for r, g, b in data if r > 12 or g > 12 or b > 12) / total

def _action_with_feedback(fn, *args, **kw) -> dict:
    before_img, _ = _capture_raw(0)
    r = fn(*args, **kw)
    time.sleep(0.5)
    after_img, after_b64 = _capture_raw(0)
    ratio = _compute_diff(before_img, after_img)
    changed = ratio > 0.001
    return {**r, "after_screenshot": after_b64, "changed": changed,
            "change_ratio": round(ratio * 100, 3)}


# ════════════════════════════════════════
#  Actions
# ════════════════════════════════════════

def _screenshot(monitor=0):
    _, b64 = _capture_raw(monitor)
    w, h = Image.open(io.BytesIO(base64.b64decode(b64))).size
    return {"data": b64, "width": w, "height": h}

def _screen_size():
    import pyautogui; w, h = pyautogui.size(); return {"width": w, "height": h}

def _get_display_info():
    import mss; ds = []
    with mss.mss() as sct:
        for i, m in enumerate(sct.monitors[1:], start=0):
            ds.append({"index": i, "width": m["width"], "height": m["height"],
                       "x": m["left"], "y": m["top"], "is_primary": i == 0})
    return ds

def _mouse_pos():
    import pyautogui; p = pyautogui.position(); return {"x": p.x, "y": p.y}

def _click(x, y, button="left", clicks=1):
    import pyautogui
    pyautogui.FAILSAFE = True
    c = _get_cursor()
    c.show_click(x, y, f"{'Double-' if clicks==2 else ''}{button.title()}")
    time.sleep(0.12)
    pyautogui.moveTo(x, y, duration=0.3)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks)
    return {"success": True, "action": "click", "x": x, "y": y}

def _click_and_type(x, y, text, press_enter=True, clicks=1):
    """Click at (x,y) to set focus, then type text, then optionally press Enter.
    ALL in one call — ensures text goes to the right window."""
    import pyautogui
    pyautogui.FAILSAFE = True
    c = _get_cursor()

    # 1. Move cursor and click to set focus
    c.show_click(x, y, f"Click -> Type")
    time.sleep(0.15)
    pyautogui.moveTo(x, y, duration=0.3)
    pyautogui.click(x=x, y=y, button="left", clicks=clicks)
    time.sleep(0.5)  # wait for focus shift

    # 2. Type text
    has_non_ascii = any(ord(ch) > 127 for ch in text)
    c.show_type(text)

    if has_non_ascii:
        import pyperclip
        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.2)
    else:
        pyautogui.typewrite(text, interval=0.02)

    # 3. Press Enter if requested
    if press_enter:
        time.sleep(0.15)
        pyautogui.press('enter')

    return {"success": True, "action": "click_and_type", "x": x, "y": y,
            "text": text, "length": len(text),
            "used_clipboard": has_non_ascii, "pressed_enter": press_enter}

def _key_press(keys, x=None, y=None):
    """Press a key/combo. If (x,y) given, clicks there first."""
    import pyautogui
    pyautogui.FAILSAFE = True
    if x is not None and y is not None:
        c = _get_cursor(); c.show_click(x, y, f"Click -> {keys}")
        time.sleep(0.15); pyautogui.moveTo(x, y, duration=0.3)
        pyautogui.click(x=x, y=y, button="left", clicks=1)
        time.sleep(0.4)
    parts = [k.strip() for k in keys.split("+")]
    if len(parts) == 1: pyautogui.press(parts[0])
    else: pyautogui.hotkey(*parts)
    return {"success": True, "action": "key_press", "keys": parts}

def _scroll(x, y, direction="down", amount=3):
    import pyautogui
    pyautogui.FAILSAFE = True
    c = _get_cursor(); c.show_click(x, y, f"Scroll {direction}")
    time.sleep(0.1); pyautogui.moveTo(x, y, duration=0.2)
    pyautogui.scroll(amount if direction == "down" else -amount, x=x, y=y)
    return {"success": True, "action": "scroll", "x": x, "y": y}

def _drag(sx, sy, ex, ey, duration=0.5):
    import pyautogui
    pyautogui.FAILSAFE = True
    c = _get_cursor(); c.show_drag(sx, sy, ex, ey) if hasattr(c, 'show_drag') else None
    time.sleep(0.1); pyautogui.moveTo(sx, sy, duration=0.3)
    pyautogui.drag(ex-sx, ey-sy, duration=duration)
    return {"success": True, "action": "drag"}

def _wait(d=1.0):
    time.sleep(d); return {"success": True}

def _open_app(name):
    mapping = {"edge": "start microsoft-edge:", "brave": "start brave",
               "chrome": "start chrome", "firefox": "start firefox",
               "notepad": "start notepad", "calc": "start calc"}
    cmd = mapping.get(name.lower(), f"start {name}")
    try:
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"success": True, "action": "open_app", "app": name}
    except Exception as e:
        return {"success": False, "action": "open_app", "app": name, "error": str(e)}


# ════════════════════════════════════════
#  MCP Server
# ════════════════════════════════════════

app = Server("computer-use")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="screenshot",
             description="Take a screenshot of the current screen. Returns the image. EXAMINE the image carefully, estimate pixel coordinates of UI elements you want to interact with, then use click_and_type with those coordinates.",
             inputSchema={"type": "object", "properties": {"monitor": {"type": "integer", "default": 0}}}),

        Tool(name="get_screen_size",
             description="Get screen width and height in pixels.",
             inputSchema={"type": "object", "properties": {}, "required": []}),

        Tool(name="get_mouse_position",
             description="Get current mouse (x,y) position.",
             inputSchema={"type": "object", "properties": {}, "required": []}),

        Tool(name="click",
             description="Click the left mouse button at (x,y). Returns after-screenshot + whether screen changed. Use this to give focus to a window or button — then follow up with click_and_type to type in it.",
             inputSchema={"type": "object",
                          "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                                         "clicks": {"type": "integer", "enum": [1, 2], "default": 1}},
                          "required": ["x", "y"]}),

        Tool(name="click_and_type",
             description="THE MAIN TEXT INPUT TOOL. Click at (x,y) to focus, then type text, then press Enter. All in one call. ALWAYS use this instead of separate click+type — it ensures text reaches the right window. Supports Chinese/emoji via clipboard. Example: click_and_type(x=400, y=60, text='douyin.com')",
             inputSchema={"type": "object",
                          "properties": {
                              "x": {"type": "integer", "description": "X pixel coordinate of the text input field"},
                              "y": {"type": "integer", "description": "Y pixel coordinate of the text input field"},
                              "text": {"type": "string", "description": "Text to type (Chinese OK)"},
                              "press_enter": {"type": "boolean", "default": True,
                                              "description": "Press Enter after typing"},
                              "clicks": {"type": "integer", "enum": [1, 2], "default": 1},
                          }, "required": ["x", "y", "text"]}),

        Tool(name="key_press",
             description="Press a key or combination like 'enter', 'ctrl+v', 'ctrl+l'. Provide (x,y) to click on the target window first so the key goes there.",
             inputSchema={"type": "object",
                          "properties": {
                              "keys": {"type": "string", "description": "Key like 'enter', 'ctrl+v'"},
                              "x": {"type": "integer"}, "y": {"type": "integer"},
                          }, "required": ["keys"]}),

        Tool(name="scroll",
             description="Scroll the mouse wheel at (x,y).",
             inputSchema={"type": "object",
                          "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                                         "direction": {"type": "string", "enum": ["up", "down"], "default": "down"},
                                         "amount": {"type": "integer", "default": 3}},
                          "required": ["x", "y"]}),

        Tool(name="drag",
             description="Drag from (start_x,start_y) to (end_x,end_y).",
             inputSchema={"type": "object",
                          "properties": {"start_x": {"type": "integer"}, "start_y": {"type": "integer"},
                                         "end_x": {"type": "integer"}, "end_y": {"type": "integer"},
                                         "duration": {"type": "number", "default": 0.5}},
                          "required": ["start_x", "start_y", "end_x", "end_y"]}),

        Tool(name="wait",
             description="Pause. Use between actions for UI to respond.",
             inputSchema={"type": "object", "properties": {"duration": {"type": "number", "default": 1.0}}}),

        Tool(name="open_app",
             description="Open an application by name: edge, brave, chrome, firefox, notepad, calc. Returns a screenshot after the app opens.",
             inputSchema={"type": "object",
                          "properties": {"name": {"type": "string", "description": "App name"}},
                          "required": ["name"]}),
    ]


@app.call_tool()
async def call_tool(name: str, args: dict[str, Any]) -> list[TextContent | ImageContent]:
    try:
        if name == "screenshot":
            r = await asyncio.to_thread(_screenshot, args.get("monitor", 0))
            return [
                TextContent(type="text",
                            text=f"Screen: {r['width']}x{r['height']}.\n"
                                 "This is your current desktop. Look at the image carefully.\n"
                                 f"Coordinates: top-left=(0,0), center=({r['width']//2},{r['height']//2}), "
                                 f"bottom-right=({r['width']},{r['height']})."),
                ImageContent(type="image", data=r["data"], mimeType="image/png")]

        elif name == "get_screen_size":
            r = await asyncio.to_thread(_screen_size)
            return [TextContent(type="text", text=f"{r['width']}x{r['height']}")]

        elif name == "get_mouse_position":
            r = await asyncio.to_thread(_mouse_pos)
            return [TextContent(type="text", text=f"({r['x']}, {r['y']})")]

        elif name == "click":
            r = await asyncio.to_thread(_action_with_feedback, _click,
                                        args["x"], args["y"], "left", args.get("clicks", 1))
            ch = "CHANGED" if r["changed"] else "NO CHANGE"
            hint = "" if r["changed"] else " Click missed target — retry with adjusted coordinates."
            return [TextContent(type="text", text=f"Click ({args['x']},{args['y']}): {ch} ({r['change_ratio']}%).{hint}"),
                    ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png")]

        elif name == "click_and_type":
            r = await asyncio.to_thread(_action_with_feedback, _click_and_type,
                                        args["x"], args["y"], args["text"],
                                        args.get("press_enter", True), args.get("clicks", 1))
            ch = "CHANGED" if r["changed"] else "NO CHANGE"
            ent = "+Enter" if r.get("pressed_enter") else ""
            clip = " (clipboard)" if r.get("used_clipboard") else ""
            hint = "" if r["changed"] else " MISSED — check coordinates and retry."
            return [TextContent(type="text",
                                text=f"click_and_type ({args['x']},{args['y']}): "
                                     f"'{args['text'][:50]}'{clip}{ent} -> {ch} ({r['change_ratio']}%).{hint}"),
                    ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png")]

        elif name == "key_press":
            kx, ky = args.get("x"), args.get("y")
            r = await asyncio.to_thread(_action_with_feedback, _key_press, args["keys"], kx, ky)
            ch = "CHANGED" if r["changed"] else "NO CHANGE"
            ctx = f" (clicked ({kx},{ky}) first)" if kx is not None else ""
            return [TextContent(type="text", text=f"Key {args['keys']}{ctx}: {ch} ({r['change_ratio']}%)."),
                    ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png")]

        elif name == "scroll":
            r = await asyncio.to_thread(_action_with_feedback, _scroll,
                                        args["x"], args["y"],
                                        args.get("direction", "down"), args.get("amount", 3))
            ch = "CHANGED" if r["changed"] else "NO CHANGE"
            return [TextContent(type="text", text=f"Scroll ({args['x']},{args['y']}): {ch} ({r['change_ratio']}%)."),
                    ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png")]

        elif name == "drag":
            r = await asyncio.to_thread(_action_with_feedback, _drag,
                                        args["start_x"], args["start_y"],
                                        args["end_x"], args["end_y"], args.get("duration", 0.5))
            ch = "CHANGED" if r["changed"] else "NO CHANGE"
            return [TextContent(type="text", text=f"Drag: {ch} ({r['change_ratio']}%)."),
                    ImageContent(type="image", data=r["after_screenshot"], mimeType="image/png")]

        elif name == "wait":
            await asyncio.to_thread(_wait, min(args.get("duration", 1.0), 10.0))
            return [TextContent(type="text", text=f"Waited {args.get('duration', 1.0)}s")]

        elif name == "open_app":
            r = await asyncio.to_thread(_open_app, args["name"])
            if r["success"]:
                _wait(2.0)
                ss = _screenshot(0)
                _get_cursor().set_status(f"Opened {args['name']}")
                return [TextContent(type="text",
                                    text=f"Opened '{args['name']}'. Current screen below. "
                                         "Now call screenshot() to see the app, then use click_and_type() to type."),
                        ImageContent(type="image", data=ss["data"], mimeType="image/png")]
            return [TextContent(type="text", text=f"FAILED to open '{args['name']}': {r.get('error')}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error("Tool '%s' failed: %s", name, e, exc_info=True)
        return [TextContent(type="text", text=f"Error: {e}")]


async def main():
    async with stdio_server() as (r, w):
        await app.run(r, w, app.create_initialization_options())

def run():
    logging.basicConfig(level=logging.WARNING)
    _get_cursor()
    asyncio.run(main())

if __name__ == "__main__":
    run()
