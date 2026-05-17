"""
Plugin SDK - Base classes, hooks, and types for plugin development.

Public API for third-party plugin developers.
"""

from src.sdk.base import BasePlugin, PluginInitError
from src.sdk.hooks import ComputerUseHookSpec, hookimpl, hookspec
from src.sdk.models import ActionRecord, DisplayInfo, Region, Screenshot
from src.sdk.types import (
    ACTION_TYPE_MAP,
    ActionType,
    Action,
    ClickAction,
    DoneAction,
    DragAction,
    KeyPressAction,
    ScrollAction,
    ScreenshotAction,
    TypeAction,
    WaitAction,
    parse_action,
)

__all__ = [
    "BasePlugin",
    "PluginInitError",
    "ComputerUseHookSpec",
    "hookimpl",
    "hookspec",
    "ActionType",
    "Action",
    "ClickAction",
    "TypeAction",
    "KeyPressAction",
    "ScrollAction",
    "DragAction",
    "WaitAction",
    "ScreenshotAction",
    "DoneAction",
    "ACTION_TYPE_MAP",
    "parse_action",
    "Region",
    "DisplayInfo",
    "Screenshot",
    "ActionRecord",
]
