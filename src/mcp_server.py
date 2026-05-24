"""
MCP Server — Computer Use for Claude Desktop.

Fully model-agnostic. Works with ANY vision-capable model via OpenAI-compatible API:
- OpenAI (GPT-4o), Ollama (llama3.2-vision, qwen-vl), vLLM, Groq, etc.

The model receives a screenshot + system prompt and returns a JSON action
with pixel coordinates. This server executes the action and loops.

Configure via environment variables or .env file:
  COMPUTER_USE_MODEL     - model name (default: gpt-4o)
  COMPUTER_USE_API_KEY   - API key
  COMPUTER_USE_BASE_URL  - API base URL (default: https://api.openai.com/v1)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ImageContent
from PIL import Image, ImageChops

logger = logging.getLogger("computer-use-mcp")

# ═════════════════════════════════════════════════════════════
#  Config — model-agnostic
# ═════════════════════════════════════════════════════════════

def _load_config() -> dict:
    """Load configuration from env vars or .env file."""
    cfg: dict[str, str] = {}

    # Read .env file
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if k.strip() not in os.environ:
                    cfg[k.strip()] = v

    # Environment overrides
    for k in os.environ:
        cfg[k] = os.environ[k]

    return cfg

_config = _load_config()

# Model backends — OpenAI-compatible
_AI_MODEL = _config.get("COMPUTER_USE_MODEL", "gpt-4o")
_AI_API_KEY = _config.get("COMPUTER_USE_API_KEY", _config.get("OPENAI_API_KEY", ""))
_AI_BASE_URL = _config.get("COMPUTER_USE_BASE_URL", _config.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))


# ═════════════════════════════════════════════════════════════
#  System prompt — tells any vision model how to output actions
# ═════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """You are a computer use agent. You control a computer by looking at screenshots and deciding where to click and what to type.

When you see a screenshot, decide the NEXT SINGLE ACTION to advance the task. Output ONLY a JSON object with no additional text, no markdown, no explanation.

Available actions:

1. Click: {"action": "click", "x": <int>, "y": <int>, "button": "left"}
2. Double-click: {"action": "double_click", "x": <int>, "y": <int>}
3. Type text: {"action": "type", "text": "<string>"}
4. Press a key: {"action": "key", "keys": "enter"}  or  {"action": "key", "keys": "ctrl+v"}  (use + for combos)
5. Scroll: {"action": "scroll", "x": <int>, "y": <int>, "direction": "up|down", "amount": <int>}
6. Drag: {"action": "drag", "start_x": <int>, "start_y": <int>, "end_x": <int>, "end_y": <int>}
7. Wait: {"action": "wait", "duration": <float>}
8. Done: {"action": "done", "summary": "<what was accomplished>"}

COORDINATES: (0,0) is the top-left corner of the screen. X increases to the right, Y increases down. Be PRECISE with pixel coordinates — look carefully at where UI elements are positioned.

TASK FLOW:
- For opening an app: click on the desktop/taskbar icon, or press Win key and type the app name
- For browser navigation: click the address bar, type the URL, press Enter
- For search: click the search box, type the query, press Enter
- For forms: click each field, type the value
- Each step: ONE action at a time. Wait for the UI to respond before the next action.

OUTPUT ONLY THE JSON. NO OTHER TEXT."""


# ═════════════════════════════════════════════════════════════
#  Virtual Cursor
# ═════════════════════════════════════════════════════════════

class VirtualCursor:
    """Transparent overlay — red arrow at the AI's cursor position."""

    def __init__(self):
        self._root: Any = None; self._canvas: Any = None
        self._thread: threading.Thread | None = None; self._running = False
        self._x = 0.0; self._y = 0.0; self._tx = 0.0; self._ty = 0.0
        self._sw = 1920; self._sh = 1080
        self._cursor_items: list = []; self._ripple_items: list = []
        self._label_id: Any = None; self._status_id: Any = None

    def start(self):
        if self._running: return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start(); time.sleep(0.4)

    def stop(self):
        self._running = False
        if self._root:
            try: self._root.after(0, self._root.destroy)
            except Exception: pass

    def show_at(self, x, y, label=""):
        self._tx, self._ty = x, y
        if label and self._root:
            self._root.after(5, lambda: self._draw_ripple(x, y, label))

    def set_status(self, text):
        if self._root: self._root.after(5, lambda: self._draw_status(text))

    def _run(self):
        import tkinter as tk
        self._root = tk.Tk(); self._root.withdraw()
        self._sw = self._root.winfo_screenwidth(); self._sh = self._root.winfo_screenheight()
        self._root = tk.Toplevel(self._root)
        self._root.title("ComputerUse"); self._root.attributes("-topmost", True)
        self._root.attributes("-transparentcolor", "#F0F0F0"); self._root.overrideredirect(True)
        self._root.geometry(f"{self._sw}x{self._sh}+0+0")
        try: self._root.attributes("-alpha", 0.80)
        except Exception: pass
        self._canvas = tk.Canvas(self._root, width=self._sw, height=self._sh,
                                 bg="#F0F0F0", highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self._draw_cursor(); self._root.after(50, self._animate)
        self._root.protocol("WM_DELETE_WINDOW", lambda: None); self._root.mainloop()

    def _draw_cursor(self):
        x, y, s = self._x, self._y, 24
        self._cursor_items.append(self._canvas.create_polygon(
            x, y, x, y+s, x+s*0.3, y+s*0.7, x+s*0.6, y+s*1.2, x+s*0.75, y+s,
            x+s*0.45, y+s*0.6, x+s, y+s*0.5, fill="#FF2222", outline="#FFF", width=3))
        self._label_id = self._canvas.create_text(x+s+8, y, text="", fill="#FFD700",
                                                   font=("Consolas",10,"bold"), anchor="w")
        self._status_id = self._canvas.create_text(10, self._sh-30, text="",
                                                    fill="#00FF88", font=("Consolas",11,"bold"), anchor="w")

    def _animate(self):
        if not self._running: return
        dx, dy = self._tx - self._x, self._ty - self._y
        if abs(dx) > 0.3 or abs(dy) > 0.3:
            self._x += dx*0.35; self._y += dy*0.35
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
        for r in [8,16,24,32]:
            self._ripple_items.append(self._canvas.create_oval(x-r,y-r,x+r,y+r,outline="#FF2222",width=3))
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


# ═════════════════════════════════════════════════════════════
#  Screen capture
# ═════════════════════════════════════════════════════════════

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
        return img, base64.b64encode(buf.getvalue()).decode("utf-8"), img.size

def _screenshot(monitor=0):
    _, b64, (w, h) = _capture_raw(monitor)
    return {"data": b64, "width": w, "height": h}


# ═════════════════════════════════════════════════════════════
#  Action execution
# ═════════════════════════════════════════════════════════════

def _click(x, y, button="left", clicks=1):
    import pyautogui
    pyautogui.FAILSAFE = True
    _get_cursor().show_at(x, y, f"{'Double-' if clicks==2 else ''}Click")
    time.sleep(0.1); pyautogui.moveTo(x, y, duration=0.3)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks)

def _type(text):
    import pyautogui
    pyautogui.FAILSAFE = True
    _get_cursor().set_status(f"Typing: {text[:30]}")
    if any(ord(c) > 127 for c in text):
        import pyperclip; pyperclip.copy(text); time.sleep(0.08)
        pyautogui.hotkey('ctrl', 'v'); time.sleep(0.15)
    else:
        pyautogui.typewrite(text, interval=0.02)

def _key(keys):
    import pyautogui
    pyautogui.FAILSAFE = True

    # Normalize: handle both string "ctrl+v" and list ["ctrl","v"]
    if isinstance(keys, list):
        parts = [str(k).strip().lower() for k in keys]
    else:
        parts = [k.strip().lower() for k in str(keys).split("+")]

    # Win key combos need system-level events via Win32 API
    if "win" in parts or "lwin" in parts or "rwin" in parts:
        import ctypes
        VK_MAP = {"win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
                  "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
                  "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
                  "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
                  "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
                  "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
                  "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
                  "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
                  "enter": 0x0D, "tab": 0x09, "escape": 0x1B, "space": 0x20,
                  "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28}
        KEYEVENTF_KEYUP = 0x0002
        for k in parts:
            vk = VK_MAP.get(k, 0)
            if vk:
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                time.sleep(0.02)
        # Release in reverse
        for k in reversed(parts):
            vk = VK_MAP.get(k, 0)
            if vk:
                time.sleep(0.02)
                ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        return

    # Regular keys via pyautogui
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)

def _scroll(x, y, direction="down", amount=3):
    import pyautogui
    pyautogui.FAILSAFE = True
    _get_cursor().show_at(x, y, f"Scroll {direction}")
    time.sleep(0.08); pyautogui.moveTo(x, y, duration=0.2)
    pyautogui.scroll(amount if direction == "down" else -amount, x=x, y=y)

def _drag(sx, sy, ex, ey, duration=0.5):
    import pyautogui
    pyautogui.FAILSAFE = True
    _get_cursor().show_at(sx, sy, "Drag start")
    time.sleep(0.08); pyautogui.moveTo(sx, sy, duration=0.3)
    pyautogui.drag(ex-sx, ey-sy, duration=duration)
    _get_cursor().show_at(ex, ey, "Drag end")

def _wait(secs): time.sleep(secs)

def _open_app(name):
    mapping = {"edge": "start microsoft-edge:", "brave": "start brave",
               "chrome": "start chrome", "firefox": "start firefox",
               "notepad": "start notepad", "calc": "start calc"}
    subprocess.Popen(mapping.get(name.lower(), f"start {name}"),
                     shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ═════════════════════════════════════════════════════════════
#  Model-agnostic AI call
# ═════════════════════════════════════════════════════════════

def _call_ai(messages: list) -> str | None:
    """Send conversation to the configured model via OpenAI-compatible API.
    Retries on rate limit with exponential backoff."""
    from openai import OpenAI

    if not _AI_API_KEY:
        return None

    client = OpenAI(base_url=_AI_BASE_URL, api_key=_AI_API_KEY)

    for attempt in range(5):
        try:
            response = client.chat.completions.create(
                model=_AI_MODEL,
                messages=messages,
                max_tokens=1024,
                temperature=0.0,
            )
            return response.choices[0].message.content
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                wait_time = min(2 ** attempt, 30)
                logger.warning("Rate limited, retrying in %ds...", wait_time)
                time.sleep(wait_time)
                continue
            logger.error("AI call failed: %s", e)
            return None
    return None


def _parse_action(raw: str) -> dict | None:
    """Parse a model response into an action dict. Handles JSON in/out of markdown fences."""
    raw = raw.strip()

    # Strip markdown fences
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', raw)
    if m: raw = m.group(1)

    # Find first JSON object
    m = re.search(r'\{[\s\S]*"action"[\s\S]*\}', raw)
    if m: raw = m.group(0)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ═════════════════════════════════════════════════════════════
#  Autonomous task loop (model-agnostic)
# ═════════════════════════════════════════════════════════════

def _run_task(task: str, max_iterations: int = 30) -> dict:
    """Run a task autonomously using system-prompt-driven Computer Use with any vision model."""
    if not _AI_API_KEY:
        return {"success": False, "error": "No API key configured.\n\n"
                "Set one of these environment variables or add to .env:\n"
                "  COMPUTER_USE_API_KEY=your-key\n"
                "  COMPUTER_USE_MODEL=gpt-4o  (or any vision model)\n"
                "  COMPUTER_USE_BASE_URL=https://api.openai.com/v1  (or Ollama: http://localhost:11434/v1)\n\n"
                "Example for Ollama: COMPUTER_USE_MODEL=llama3.2-vision, COMPUTER_USE_BASE_URL=http://localhost:11434/v1, COMPUTER_USE_API_KEY=ollama"}

    _get_cursor().set_status(f"Task: {task[:60]}")

    # Get screen dimensions
    _, b64, (w, h) = _capture_raw(0)
    actions_log = []
    last_b64 = b64

    # Build message history
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "text", "text": f"Task: {task}\n\nScreen size: {w}x{h} pixels.\n\nHere is the first screenshot. What is the first action? Reply with ONLY the JSON action."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]},
    ]

    for i in range(max_iterations):
        _get_cursor().set_status(f"Iter {i+1}/{max_iterations}")

        # Call the AI model
        raw = _call_ai(messages)
        if raw is None:
            return {"success": False, "error": f"AI model returned nothing at iteration {i+1}. "
                    f"Check your API key and model accessibility.",
                    "actions": actions_log, "last_screenshot": last_b64}

        action = _parse_action(raw)
        if action is None:
            # Model didn't return valid JSON — add a correction message
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": [{"type": "text",
                             "text": "That was not valid JSON. Output ONLY a JSON object with an 'action' field. Example: {\"action\": \"click\", \"x\": 100, \"y\": 200}"}]})
            continue

        a = action.get("action", "")

        # Check for done
        if a == "done":
            summary = action.get("summary", "Done")
            return {"success": True, "summary": summary,
                    "iterations": i + 1, "actions": actions_log,
                    "last_screenshot": last_b64}

        # Validate action before executing
        desc = ""
        try:
            if a in ("click", "double_click"):
                # Extract coordinates — handle all formats models might use:
                #   {"x": 100, "y": 200}, {"x": [165,30]}, {"coordinate": [100,200]},
                #   {"x": [100], "y": [200]}, {"position": [100,200]}
                x_raw = action.get("x"); y_raw = action.get("y")
                coord_raw = action.get("coordinate") or action.get("coordinates") or action.get("position")

                # Case 1: {"x": [165, 30]} — x is a 2-element coordinate array
                if isinstance(x_raw, (list, tuple)) and len(x_raw) >= 2 and y_raw is None:
                    x, y = int(x_raw[0]), int(x_raw[1])
                # Case 2: {"coordinate": [100, 200]}
                elif coord_raw and isinstance(coord_raw, (list, tuple)) and len(coord_raw) >= 2:
                    x, y = int(coord_raw[0]), int(coord_raw[1])
                # Case 3: {"x": 100, "y": 200} or {"x": [100], "y": [200]}
                elif x_raw is not None and y_raw is not None:
                    x = int(x_raw[0]) if isinstance(x_raw, list) and x_raw else int(x_raw)
                    y = int(y_raw[0]) if isinstance(y_raw, list) and y_raw else int(y_raw)
                else:
                    raise ValueError(f"Bad coordinates: x={x_raw}, y={y_raw}, coord={coord_raw}")
                clk = 2 if a == "double_click" else 1
                btn = action.get("button", "left")
                _click(x, y, btn if btn in ("left","right","middle") else "left", clk)
                desc = f"Click ({x},{y})"

            elif a == "type":
                _type(action.get("text", ""))
                desc = f"Type: '{str(action.get('text',''))[:30]}'"

            elif a == "key":
                _key(action.get("keys", ""))
                desc = f"Key: {action.get('keys','')}"

            elif a == "scroll":
                x = action.get("x", 0); y = action.get("y", 0)
                if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                    raise ValueError(f"Invalid scroll coordinates: {x}, {y}")
                _scroll(int(x), int(y), action.get("direction", "down"), action.get("amount", 3))
                desc = f"Scroll {action.get('direction','down')}"

            elif a == "drag":
                _drag(int(action.get("start_x", 0)), int(action.get("start_y", 0)),
                      int(action.get("end_x", 0)), int(action.get("end_y", 0)),
                      float(action.get("duration", 0.5)))
                desc = "Drag"

            elif a == "wait":
                _wait(min(float(action.get("duration", 1.0)), 10.0))
                desc = f"Wait {action.get('duration',1)}s"

            else:
                desc = f"Unknown: {a}"

            actions_log.append(desc)
            logger.info("Step %d: %s", i+1, desc)

        except Exception as e:
            logger.error("Action failed: %s", e)
            desc = f"Error: {e}"
            actions_log.append(desc)
            # Tell the model the action failed so it can try a different approach
            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
            messages.append({"role": "user", "content": [
                {"type": "text", "text": f"Error executing that action: {e}. Try a different approach or adjust the action format."}
            ]})
            continue

        # Wait for UI, capture new screenshot
        time.sleep(0.8)
        _, b64, (w, h) = _capture_raw(0)
        last_b64 = b64

        # Add to conversation
        messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
        messages.append({"role": "user", "content": [
            {"type": "text", "text": f"Here is the updated screen after '{desc}'. What is the next action? Output ONLY the JSON action."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]})

    _get_cursor().set_status("Max iterations reached")
    return {"success": len(actions_log) > 0,
            "summary": f"Reached max {max_iterations} iterations",
            "iterations": len(actions_log), "actions": actions_log,
            "last_screenshot": last_b64}


# ═════════════════════════════════════════════════════════════
#  MCP Server
# ═════════════════════════════════════════════════════════════

app = Server("computer-use")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="run_task",
             description="""Execute a task fully autonomously. Just describe what you want — the AI
looks at screenshots, finds UI elements, clicks, types, and verifies automatically.
Works with ANY vision model (GPT-4o, llama3.2-vision, qwen-vl, etc.).

Example: run_task("Open Edge browser, go to douyin.com, search for 影视飓风, click the first video")

Configure in .env:
  COMPUTER_USE_MODEL=gpt-4o
  COMPUTER_USE_API_KEY=your-key
  COMPUTER_USE_BASE_URL=https://api.openai.com/v1""",
             inputSchema={"type": "object",
                          "properties": {
                              "task": {"type": "string", "description": "Natural language task"},
                              "max_iterations": {"type": "integer", "default": 30},
                          }, "required": ["task"]}),

        Tool(name="screenshot",
             description="Capture the current screen.",
             inputSchema={"type": "object",
                          "properties": {"monitor": {"type": "integer", "default": 0}}}),

        Tool(name="click",
             description="Click at (x,y) coordinates.",
             inputSchema={"type": "object",
                          "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                                         "button": {"type": "string", "enum": ["left","right","middle"], "default": "left"},
                                         "clicks": {"type": "integer", "enum": [1,2], "default": 1}},
                          "required": ["x","y"]}),

        Tool(name="click_and_type",
             description="Click at (x,y) to focus, then type text, then press Enter.",
             inputSchema={"type": "object",
                          "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                                         "text": {"type": "string"},
                                         "press_enter": {"type": "boolean", "default": True}},
                          "required": ["x","y","text"]}),

        Tool(name="key_press",
             description="Press a key or combination like 'enter', 'ctrl+v'.",
             inputSchema={"type": "object",
                          "properties": {"keys": {"type": "string"},
                                         "x": {"type": "integer"}, "y": {"type": "integer"}},
                          "required": ["keys"]}),

        Tool(name="scroll",
             description="Scroll the mouse wheel at (x,y).",
             inputSchema={"type": "object",
                          "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                                         "direction": {"type": "string", "enum": ["up","down"], "default": "down"},
                                         "amount": {"type": "integer", "default": 3}},
                          "required": ["x","y"]}),

        Tool(name="drag",
             description="Drag mouse from (sx,sy) to (ex,ey).",
             inputSchema={"type": "object",
                          "properties": {"start_x":{"type":"integer"},"start_y":{"type":"integer"},
                                         "end_x":{"type":"integer"},"end_y":{"type":"integer"},
                                         "duration":{"type":"number","default":0.5}},
                          "required": ["start_x","start_y","end_x","end_y"]}),

        Tool(name="wait",
             description="Pause for N seconds.",
             inputSchema={"type": "object",
                          "properties": {"duration": {"type": "number", "default": 1.0}}}),

        Tool(name="open_app",
             description="Open an app by name: edge, brave, chrome, firefox, notepad, calc.",
             inputSchema={"type": "object",
                          "properties": {"name": {"type": "string"}},
                          "required": ["name"]}),
    ]


@app.call_tool()
async def call_tool(name: str, args: dict[str, Any]) -> list[TextContent | ImageContent]:
    try:
        if name == "run_task":
            task = args["task"]; max_it = args.get("max_iterations", 30)
            _get_cursor().set_status(f"Running: {task[:50]}")
            r = await asyncio.to_thread(_run_task, task, max_it)

            if not r.get("success"):
                return [TextContent(type="text", text=f"FAILED: {r.get('error','')}")]

            summary = r.get("summary", "Done")
            acts = r.get("actions", [])
            lines = f"DONE: {summary}\n\nSteps ({r.get('iterations',0)}):\n" + \
                    "\n".join(f"  {i+1}. {a}" for i,a in enumerate(acts))
            return [TextContent(type="text", text=lines),
                    ImageContent(type="image", data=r["last_screenshot"], mimeType="image/png")]

        elif name == "screenshot":
            r = await asyncio.to_thread(_screenshot, args.get("monitor", 0))
            return [TextContent(type="text",
                                text=f"Screen: {r['width']}x{r['height']}. "
                                     f"(0,0)→({r['width']},{r['height']})."),
                    ImageContent(type="image", data=r["data"], mimeType="image/png")]

        elif name == "click":
            await asyncio.to_thread(_click, args["x"], args["y"],
                                     args.get("button","left"), args.get("clicks",1))
            time.sleep(0.4); ss = _screenshot(0)
            _get_cursor().set_status(f"Click ({args['x']},{args['y']})")
            return [TextContent(type="text", text=f"Clicked ({args['x']},{args['y']})."),
                    ImageContent(type="image", data=ss["data"], mimeType="image/png")]

        elif name == "click_and_type":
            await asyncio.to_thread(_click, args["x"], args["y"], "left", args.get("clicks",1))
            time.sleep(0.5); await asyncio.to_thread(_type, args["text"])
            if args.get("press_enter", True):
                time.sleep(0.15); await asyncio.to_thread(_key, "enter")
            time.sleep(0.4); ss = _screenshot(0)
            _get_cursor().set_status(f"Typed at ({args['x']},{args['y']})")
            return [TextContent(type="text", text=f"Click+Type at ({args['x']},{args['y']}): '{args['text'][:40]}'"),
                    ImageContent(type="image", data=ss["data"], mimeType="image/png")]

        elif name == "key_press":
            kx, ky = args.get("x"), args.get("y")
            if kx is not None: await asyncio.to_thread(_click, kx, ky, "left", 1); time.sleep(0.4)
            await asyncio.to_thread(_key, args["keys"])
            time.sleep(0.4); ss = _screenshot(0)
            return [TextContent(type="text", text=f"Key: {args['keys']}"),
                    ImageContent(type="image", data=ss["data"], mimeType="image/png")]

        elif name == "scroll":
            await asyncio.to_thread(_scroll, args["x"], args["y"],
                                     args.get("direction","down"), args.get("amount",3))
            time.sleep(0.3); ss = _screenshot(0)
            return [TextContent(type="text", text=f"Scrolled ({args['x']},{args['y']})."),
                    ImageContent(type="image", data=ss["data"], mimeType="image/png")]

        elif name == "drag":
            await asyncio.to_thread(_drag, args["sx"], args["sy"],
                                     args["ex"], args["ey"], args.get("duration",0.5))
            time.sleep(0.3); ss = _screenshot(0)
            return [TextContent(type="text", text="Dragged."),
                    ImageContent(type="image", data=ss["data"], mimeType="image/png")]

        elif name == "wait":
            await asyncio.to_thread(_wait, min(args.get("duration",1.0), 10.0))
            return [TextContent(type="text", text=f"Waited {args.get('duration',1)}s")]

        elif name == "open_app":
            await asyncio.to_thread(_open_app, args["name"])
            _wait(2.0); ss = _screenshot(0)
            _get_cursor().set_status(f"Opened {args['name']}")
            return [TextContent(type="text", text=f"Opened '{args['name']}'."),
                    ImageContent(type="image", data=ss["data"], mimeType="image/png")]

        else:
            return [TextContent(type="text", text=f"Unknown: {name}")]

    except Exception as e:
        logger.error("%s failed: %s", name, e, exc_info=True)
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
