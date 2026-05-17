"""
Screenshot and display data types for Computer Use Plugin.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Region(BaseModel):
    """
    A rectangular region on the screen.

    Attributes:
        x: Left edge in pixels.
        y: Top edge in pixels.
        width: Width in pixels.
        height: Height in pixels.
    """

    x: int
    y: int
    width: int
    height: int


class DisplayInfo(BaseModel):
    """
    Information about a connected display.

    Attributes:
        index: Display index (0 = primary).
        width: Resolution width in pixels.
        height: Resolution height in pixels.
        x: Position X offset in the virtual screen.
        y: Position Y offset in the virtual screen.
        is_primary: Whether this is the primary display.
        dpi_scale: DPI scaling factor (1.0 = 100%).
    """

    index: int
    width: int
    height: int
    x: int = 0
    y: int = 0
    is_primary: bool = False
    dpi_scale: float = 1.0


class Screenshot(BaseModel):
    """
    Captured screenshot with metadata.

    Attributes:
        data: Base64-encoded PNG image data.
        width: Image width in pixels.
        height: Image height in pixels.
        monitor: Which monitor was captured (0 = primary).
        region: Optional region that was captured.
        timestamp: Unix timestamp when captured.
    """

    data: str
    width: int
    height: int
    monitor: int = 0
    region: Region | None = None
    timestamp: float = 0.0

    model_config = {"arbitrary_types_allowed": True}


class ActionRecord(BaseModel):
    """
    Record of a single action execution for audit and replay.

    Attributes:
        iteration: Loop iteration number.
        action: The action that was executed.
        screenshot_before: Base64 screenshot before the action.
        screenshot_after: Base64 screenshot after the action, or None.
        timestamp: Unix timestamp when the action was executed.
        duration_ms: How long the action took to execute in milliseconds.
        error: Error message if the action failed, or None.
    """

    iteration: int
    action: dict[str, Any]
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    timestamp: float = 0.0
    duration_ms: float = 0.0
    error: str | None = None
