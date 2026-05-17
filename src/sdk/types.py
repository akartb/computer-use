"""
Action type system for Computer Use Plugin.

Defines all structured action types that flow through the observe-reason-act loop.
Every action is a pydantic model for validation, serialization, and schema generation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Enumeration of all supported action types."""

    CLICK = "click"
    TYPE = "type"
    KEY_PRESS = "key_press"
    SCROLL = "scroll"
    DRAG = "drag"
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    DONE = "done"


class MouseButton(str, Enum):
    """Mouse button options."""

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class ScrollDirection(str, Enum):
    """Scroll direction options."""

    UP = "up"
    DOWN = "down"


class Action(BaseModel):
    """
    Base action model representing a single action to execute on the computer.

    Attributes:
        type: The action type identifier.
        parameters: Type-specific parameters as a dictionary.
        confidence: Model confidence score between 0.0 and 1.0.
        reasoning: Explanation of why this action was chosen.
    """

    type: ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasoning: str = Field(default="")


class ClickAction(Action):
    """
    Mouse click action at specified coordinates.

    Parameters:
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.
        button: Mouse button to click ('left', 'right', 'middle').
        clicks: Number of clicks (1=single, 2=double, 3=triple).
    """

    type: Literal[ActionType.CLICK] = ActionType.CLICK
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "x": 0,
        "y": 0,
        "button": "left",
        "clicks": 1,
    })


class TypeAction(Action):
    """
    Keyboard text input action.

    Parameters:
        text: The text string to type character by character.
    """

    type: Literal[ActionType.TYPE] = ActionType.TYPE
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "text": "",
    })


class KeyPressAction(Action):
    """
    Key combination press action.

    Parameters:
        keys: List of key names to press simultaneously, e.g. ["ctrl", "c"].
    """

    type: Literal[ActionType.KEY_PRESS] = ActionType.KEY_PRESS
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "keys": [],
    })


class ScrollAction(Action):
    """
    Mouse scroll action at specified coordinates.

    Parameters:
        x: Horizontal pixel coordinate.
        y: Vertical pixel coordinate.
        direction: Scroll direction ('up' or 'down').
        amount: Number of scroll steps.
    """

    type: Literal[ActionType.SCROLL] = ActionType.SCROLL
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "x": 0,
        "y": 0,
        "direction": "down",
        "amount": 3,
    })


class DragAction(Action):
    """
    Mouse drag action from one position to another.

    Parameters:
        start_x: Starting horizontal coordinate.
        start_y: Starting vertical coordinate.
        end_x: Ending horizontal coordinate.
        end_y: Ending vertical coordinate.
        duration: Duration of the drag in seconds.
    """

    type: Literal[ActionType.DRAG] = ActionType.DRAG
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "start_x": 0,
        "start_y": 0,
        "end_x": 0,
        "end_y": 0,
        "duration": 0.5,
    })


class WaitAction(Action):
    """
    Wait action - pause before the next step.

    Parameters:
        duration: Wait time in seconds.
    """

    type: Literal[ActionType.WAIT] = ActionType.WAIT
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "duration": 1.0,
    })


class ScreenshotAction(Action):
    """
    Screenshot action - request a fresh screenshot for re-evaluation.

    This is used when the model needs to re-observe the current state
    without performing any input action.
    """

    type: Literal[ActionType.SCREENSHOT] = ActionType.SCREENSHOT
    parameters: dict[str, Any] = Field(default_factory=dict)


class DoneAction(Action):
    """
    Task completion signal.

    Parameters:
        summary: Summary of what was accomplished.
    """

    type: Literal[ActionType.DONE] = ActionType.DONE
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "summary": "",
    })


ACTION_TYPE_MAP: dict[ActionType, type[Action]] = {
    ActionType.CLICK: ClickAction,
    ActionType.TYPE: TypeAction,
    ActionType.KEY_PRESS: KeyPressAction,
    ActionType.SCROLL: ScrollAction,
    ActionType.DRAG: DragAction,
    ActionType.WAIT: WaitAction,
    ActionType.SCREENSHOT: ScreenshotAction,
    ActionType.DONE: DoneAction,
}


def parse_action(data: dict[str, Any]) -> Action:
    """
    Parse a raw dictionary into the appropriate Action subclass.

    Args:
        data: Raw dictionary containing at least a 'type' key.

    Returns:
        An instance of the corresponding Action subclass.

    Raises:
        ValueError: If the action type is unknown.
    """
    action_type = data.get("type")
    if action_type is None:
        raise ValueError("Action data must contain a 'type' field")

    try:
        action_type = ActionType(action_type)
    except ValueError:
        raise ValueError(f"Unknown action type: {action_type}") from None

    action_cls = ACTION_TYPE_MAP.get(action_type, Action)
    return action_cls.model_validate(data)
