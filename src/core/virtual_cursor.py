"""
Virtual Cursor Overlay for Computer Use Plugin.

Displays a transparent, always-on-top, click-through overlay window
that shows the AI's mouse movements and actions in real-time.

Key features:
- Animated virtual cursor that follows AI's target coordinates
- Visual feedback for clicks (ripple effect), typing (text display), scrolling
- Completely transparent to mouse events (click-through) - doesn't interfere with real mouse
- Always on top of all windows
- Shows action labels and status information

Uses tkinter (Python built-in) for maximum compatibility - no external GUI dependencies.
"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from typing import Any, Callable

from src.sdk.types import ActionType

logger = logging.getLogger(__name__)


class VirtualCursorOverlay:
    """
    Transparent overlay window showing AI's virtual cursor and actions.

    Creates a full-screen transparent tkinter window that:
    - Shows a custom-drawn cursor at the AI's target position
    - Animates cursor movement smoothly
    - Displays click ripples, typing indicators, scroll arrows
    - Passes all mouse events through to windows below (click-through)
    - Stays on top of all other windows

    Attributes:
        _root: tkinter root window.
        _canvas: tkinter Canvas for drawing.
        _cursor_x: Current virtual cursor X position.
        _cursor_y: Current virtual cursor Y position.
        _target_x: Target X position for animation.
        _target_y: Target Y position for animation.
        _visible: Whether the overlay is currently shown.
        _action_label: Current action description text.
        _animation_id: tkinter after() ID for animation loop.
        _ripple_items: List of canvas item IDs for click ripple effects.
    """

    CURSOR_SIZE = 20
    CURSOR_COLOR = "#FF4444"
    CURSOR_OUTLINE = "#FFFFFF"
    RIPPLE_COLOR = "#FF4444"
    LABEL_COLOR = "#FFD700"
    STATUS_COLOR = "#00FF88"
    ANIMATION_STEPS = 15
    ANIMATION_INTERVAL = 16  # ~60fps

    def __init__(self) -> None:
        self._root: Any = None
        self._canvas: Any = None
        self._cursor_x: float = 0
        self._cursor_y: float = 0
        self._target_x: float = 0
        self._target_y: float = 0
        self._visible: bool = False
        self._action_label: str = ""
        self._status_text: str = ""
        self._animation_id: Any = None
        self._ripple_items: list[Any] = []
        self._cursor_items: list[Any] = []
        self._label_item: Any = None
        self._status_item: Any = None
        self._thread: threading.Thread | None = None
        self._running: bool = False
        self._screen_width: int = 1920
        self._screen_height: int = 1080

    def start(self) -> None:
        """
        Start the overlay in a background thread.

        The tkinter mainloop runs in a daemon thread so it doesn't
        block the main asyncio event loop.
        """
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()
        logger.info("Virtual cursor overlay started")

    def stop(self) -> None:
        """
        Stop the overlay and clean up resources.
        """
        self._running = False
        if self._root is not None:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:
                pass
        logger.info("Virtual cursor overlay stopped")

    def _run_tk(self) -> None:
        """
        Run the tkinter mainloop in the background thread.
        """
        import tkinter as tk

        self._root = tk.Tk()
        self._root.withdraw()

        self._screen_width = self._root.winfo_screenwidth()
        self._screen_height = self._root.winfo_screenheight()

        self._setup_window()
        self._create_cursor()

        self._root.after(100, self._animation_loop)
        self._visible = True

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.mainloop()

    def _setup_window(self) -> None:
        """
        Configure the overlay window as transparent, always-on-top, click-through.
        """
        import tkinter as tk

        self._root = tk.Toplevel(self._root)
        self._root.title("ComputerUse-Overlay")

        self._root.attributes("-topmost", True)
        self._root.attributes("-transparentcolor", "#F0F0F0")

        self._root.overrideredirect(True)

        self._root.geometry(f"{self._screen_width}x{self._screen_height}+0+0")

        try:
            self._root.attributes("-alpha", 0.85)
        except Exception:
            pass

        self._canvas = tk.Canvas(
            self._root,
            width=self._screen_width,
            height=self._screen_height,
            bg="#F0F0F0",
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill="both", expand=True)

        try:
            import ctypes
            hwnd = int(self._root.frame(), 16)
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        except Exception as e:
            logger.debug("Could not set click-through on non-Windows: %s", e)

    def _create_cursor(self) -> None:
        """
        Draw the initial virtual cursor shape on the canvas.
        """
        x, y = self._cursor_x, self._cursor_y
        s = self.CURSOR_SIZE

        self._cursor_items = []

        self._cursor_items.append(
            self._canvas.create_polygon(
                x, y,
                x, y + s,
                x + s * 0.3, y + s * 0.7,
                x + s * 0.6, y + s * 1.1,
                x + s * 0.75, y + s * 1.0,
                x + s * 0.45, y + s * 0.6,
                x + s, y + s * 0.6,
                fill=self.CURSOR_COLOR,
                outline=self.CURSOR_OUTLINE,
                width=2,
            )
        )

        self._label_item = self._canvas.create_text(
            x + s + 5, y + s // 2,
            text="",
            fill=self.LABEL_COLOR,
            font=("Consolas", 10, "bold"),
            anchor="w",
        )

        self._status_item = self._canvas.create_text(
            10, self._screen_height - 30,
            text="",
            fill=self.STATUS_COLOR,
            font=("Consolas", 11, "bold"),
            anchor="w",
        )

    def move_cursor(self, x: float, y: float, label: str = "") -> None:
        """
        Animate the virtual cursor moving to a new position.

        Args:
            x: Target X coordinate.
            y: Target Y coordinate.
            label: Optional action label to display next to cursor.
        """
        self._target_x = x
        self._target_y = y
        self._action_label = label

    def show_click(self, x: float, y: float, button: str = "left", clicks: int = 1) -> None:
        """
        Show a click ripple effect at the specified position.

        Args:
            x: Click X coordinate.
            y: Click Y coordinate.
            button: Mouse button used.
            clicks: Number of clicks.
        """
        if self._root is None:
            return

        color = "#FF4444" if button == "left" else "#4444FF" if button == "right" else "#44FF44"
        label = f"{'Double ' if clicks == 2 else 'Triple ' if clicks == 3 else ''}{button.title()} Click"

        self._root.after(0, lambda: self._draw_click_ripple(x, y, color, label))

    def show_type(self, text: str) -> None:
        """
        Show a typing indicator near the cursor.

        Args:
            text: The text being typed.
        """
        if self._root is None:
            return

        display_text = text[:30] + ("..." if len(text) > 30 else "")
        label = f'Type: "{display_text}"'
        self._root.after(0, lambda: self._update_label(label))

    def show_scroll(self, direction: str, amount: int = 3) -> None:
        """
        Show a scroll indicator.

        Args:
            direction: Scroll direction ('up' or 'down').
            amount: Scroll amount.
        """
        if self._root is None:
            return

        arrow = "↑" if direction == "up" else "↓"
        label = f"Scroll {arrow} x{amount}"
        self._root.after(0, lambda: self._update_label(label))

    def show_key_press(self, keys: list[str]) -> None:
        """
        Show a key combination indicator.

        Args:
            keys: List of key names.
        """
        if self._root is None:
            return

        label = " + ".join(k.title() for k in keys)
        self._root.after(0, lambda: self._update_label(f"[{label}]"))

    def show_drag(self, start_x: float, start_y: float, end_x: float, end_y: float) -> None:
        """
        Show a drag indicator from start to end position.

        Args:
            start_x: Start X coordinate.
            start_y: Start Y coordinate.
            end_x: End X coordinate.
            end_y: End Y coordinate.
        """
        if self._root is None:
            return

        self._root.after(0, lambda: self._draw_drag_line(start_x, start_y, end_x, end_y))

    def show_action(self, action: dict[str, Any]) -> None:
        """
        Show visual feedback for any action type.

        Args:
            action: Action dict with 'type' and 'parameters'.
        """
        action_type = action.get("type", "")
        params = action.get("parameters", {})

        if action_type == ActionType.CLICK:
            self.move_cursor(params.get("x", 0), params.get("y", 0))
            self.show_click(
                params.get("x", 0), params.get("y", 0),
                params.get("button", "left"), params.get("clicks", 1),
            )
        elif action_type == ActionType.TYPE:
            self.show_type(params.get("text", ""))
        elif action_type == ActionType.KEY_PRESS:
            self.show_key_press(params.get("keys", []))
        elif action_type == ActionType.SCROLL:
            self.move_cursor(params.get("x", 0), params.get("y", 0))
            self.show_scroll(params.get("direction", "down"), params.get("amount", 3))
        elif action_type == ActionType.DRAG:
            self.show_drag(
                params.get("start_x", 0), params.get("start_y", 0),
                params.get("end_x", 0), params.get("end_y", 0),
            )

    def set_status(self, text: str) -> None:
        """
        Update the status bar text at the bottom of the overlay.

        Args:
            text: Status text to display.
        """
        self._status_text = text
        if self._root is not None:
            self._root.after(0, lambda: self._update_status(text))

    def _animation_loop(self) -> None:
        """
        Smoothly animate the cursor toward the target position.
        Called repeatedly by tkinter's after() mechanism.
        """
        if not self._running:
            return

        dx = self._target_x - self._cursor_x
        dy = self._target_y - self._cursor_y

        if abs(dx) > 1 or abs(dy) > 1:
            step = 0.25
            self._cursor_x += dx * step
            self._cursor_y += dy * step
            self._redraw_cursor()

        if self._running and self._root is not None:
            self._animation_id = self._root.after(self.ANIMATION_INTERVAL, self._animation_loop)

    def _redraw_cursor(self) -> None:
        """
        Redraw the cursor at its current animated position.
        """
        if self._canvas is None:
            return

        x, y = self._cursor_x, self._cursor_y
        s = self.CURSOR_SIZE

        for item in self._cursor_items:
            self._canvas.delete(item)
        self._cursor_items.clear()

        self._cursor_items.append(
            self._canvas.create_polygon(
                x, y,
                x, y + s,
                x + s * 0.3, y + s * 0.7,
                x + s * 0.6, y + s * 1.1,
                x + s * 0.75, y + s * 1.0,
                x + s * 0.45, y + s * 0.6,
                x + s, y + s * 0.6,
                fill=self.CURSOR_COLOR,
                outline=self.CURSOR_OUTLINE,
                width=2,
            )
        )

        if self._label_item:
            self._canvas.coords(self._label_item, x + s + 5, y + s // 2)

    def _draw_click_ripple(self, x: float, y: float, color: str, label: str) -> None:
        """
        Draw an expanding ripple effect at the click position.

        Args:
            x: Click X coordinate.
            y: Click Y coordinate.
            color: Ripple color.
            label: Action label text.
        """
        self._update_label(label)

        for r in [8, 16, 24, 32]:
            item = self._canvas.create_oval(
                x - r, y - r, x + r, y + r,
                outline=color, width=2,
            )
            self._ripple_items.append(item)

        self._root.after(400, lambda: self._clear_ripples())

    def _draw_drag_line(self, sx: float, sy: float, ex: float, ey: float) -> None:
        """
        Draw a drag indicator line from start to end.

        Args:
            sx: Start X.
            sy: Start Y.
            ex: End X.
            ey: End Y.
        """
        self._update_label("Drag")

        self._canvas.create_line(sx, sy, ex, ey, fill="#FF8800", width=3, dash=(6, 4), tags="drag_line")
        self._canvas.create_oval(ex - 6, ey - 6, ex + 6, ey + 6, fill="#FF8800", outline="", tags="drag_line")

        self._root.after(800, lambda: self._canvas.delete("drag_line"))

    def _clear_ripples(self) -> None:
        """
        Remove all ripple effect items from the canvas.
        """
        for item in self._ripple_items:
            try:
                self._canvas.delete(item)
            except Exception:
                pass
        self._ripple_items.clear()

    def _update_label(self, text: str) -> None:
        """
        Update the action label text next to the cursor.

        Args:
            text: New label text.
        """
        if self._label_item and self._canvas:
            self._canvas.itemconfig(self._label_item, text=text)
            self._root.after(1500, lambda: self._canvas.itemconfig(self._label_item, text=""))

    def _update_status(self, text: str) -> None:
        """
        Update the status bar text.

        Args:
            text: New status text.
        """
        if self._status_item and self._canvas:
            self._canvas.itemconfig(self._status_item, text=f"🤖 {text}")

    def _on_close(self) -> None:
        """
        Handle window close event.
        """
        self._running = False
        self._visible = False
