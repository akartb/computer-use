"""
Configuration management for Computer Use Plugin.

Loads, validates, and provides access to YAML configuration files.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "default.yaml"


class CoreConfig(BaseModel):
    """
    Core engine configuration.

    Attributes:
        max_iterations: Maximum action loop iterations.
        action_delay: Minimum delay between actions in seconds.
        screenshot_quality: Image quality (1-100).
        screenshot_format: Image format ('png' or 'jpeg').
    """

    max_iterations: int = Field(default=50, ge=1, le=500)
    action_delay: float = Field(default=0.5, ge=0.0, le=10.0)
    screenshot_quality: int = Field(default=85, ge=1, le=100)
    screenshot_format: str = Field(default="png")

    @field_validator("screenshot_format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate screenshot format is png or jpeg."""
        if v not in ("png", "jpeg"):
            raise ValueError("screenshot_format must be 'png' or 'jpeg'")
        return v


class AIConfig(BaseModel):
    """
    AI backend configuration.

    Attributes:
        default_backend: Name of the default AI backend.
        backends: Dictionary of backend-specific configurations.
    """

    default_backend: str = "openai"
    backends: dict[str, dict[str, Any]] = Field(default_factory=lambda: {
        "openai": {
            "model": "computer-use-preview",
            "api_key_env": "OPENAI_API_KEY",
            "temperature": 0.0,
        },
        "anthropic": {
            "model": "claude-sonnet-4-20250514",
            "api_key_env": "ANTHROPIC_API_KEY",
            "temperature": 0.0,
        },
        "ollama": {
            "model": "llama3.2-vision",
            "base_url": "http://localhost:11434",
        },
    })


class SafetyConfig(BaseModel):
    """
    Safety guardrail configuration.

    Attributes:
        enabled: Whether safety validation is active.
        mode: Safety mode ('auto', 'confirm', 'sandbox').
        blocked_apps: List of application names to block.
        blocked_keywords: List of UI element keywords to block.
        confidence_threshold: Minimum AI confidence score (0.0-1.0).
        require_confirmation_for: Action types requiring human confirmation.
    """

    enabled: bool = True
    mode: str = "confirm"
    blocked_apps: list[str] = Field(default_factory=lambda: [
        "Task Manager",
        "Registry Editor",
        "System Preferences",
    ])
    blocked_keywords: list[str] = Field(default_factory=lambda: [
        "delete",
        "format",
        "remove",
    ])
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    require_confirmation_for: list[str] = Field(default_factory=lambda: [
        "type",
        "key_press",
    ])

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Validate safety mode is one of the allowed values."""
        if v not in ("auto", "confirm", "sandbox"):
            raise ValueError("safety mode must be 'auto', 'confirm', or 'sandbox'")
        return v


class ScreenConfig(BaseModel):
    """
    Screen capture configuration.

    Attributes:
        capture_method: Capture backend name.
        monitor: Default monitor index.
        dpi_aware: Whether to handle DPI scaling.
    """

    capture_method: str = "mss"
    monitor: int = 0
    dpi_aware: bool = True


class InputConfig(BaseModel):
    """
    Input control configuration.

    Attributes:
        backend: Input backend name.
        typing_interval: Delay between keystrokes in seconds.
        move_duration: Duration of mouse movement in seconds.
    """

    backend: str = "pyautogui"
    typing_interval: float = 0.02
    move_duration: float = 0.3


class LoggingConfig(BaseModel):
    """
    Logging configuration.

    Attributes:
        level: Log level name.
        save_screenshots: Whether to save screenshots to disk.
        screenshot_dir: Directory path for saved screenshots.
        action_log: File path for action log (JSONL format).
    """

    level: str = "INFO"
    save_screenshots: bool = True
    screenshot_dir: str = "./logs/screenshots"
    action_log: str = "./logs/actions.jsonl"


class AppConfig(BaseModel):
    """
    Root application configuration combining all sub-configurations.

    Attributes:
        core: Core engine settings.
        ai: AI backend settings.
        safety: Safety guardrail settings.
        screen: Screen capture settings.
        input: Input control settings.
        logging: Logging settings.
        plugins: Plugin-specific configuration overrides.
    """

    core: CoreConfig = Field(default_factory=CoreConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    screen: ScreenConfig = Field(default_factory=ScreenConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    plugins: dict[str, dict[str, Any]] = Field(default_factory=dict)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """
    Load configuration from a YAML file with environment variable substitution.

    Falls back to default values for any missing fields. Supports
    ${ENV_VAR} syntax for environment variable references in the YAML.

    Args:
        config_path: Path to the YAML configuration file.
                     Defaults to config/default.yaml.

    Returns:
        Validated AppConfig instance.
    """
    if config_path is None:
        config_path = DEFAULT_CONFIG_PATH

    config_path = Path(config_path)

    if not config_path.exists():
        logger.info("Config file not found at %s, using defaults", config_path)
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    raw = _substitute_env_vars(raw)

    try:
        config = AppConfig.model_validate(raw)
        logger.info("Configuration loaded from %s", config_path)
        return config
    except Exception as e:
        logger.warning("Config validation failed: %s, using defaults", e)
        return AppConfig()


def _substitute_env_vars(data: Any) -> Any:
    """
    Recursively substitute ${ENV_VAR} references with environment variable values.

    Args:
        data: The data structure to process (dict, list, or scalar).

    Returns:
        The data structure with environment variables substituted.
    """
    if isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        env_var = data[2:-1]
        value = os.environ.get(env_var, data)
        return value
    return data


def save_default_config(output_path: str | Path) -> None:
    """
    Generate and save a default configuration file.

    Args:
        output_path: Path where the default config will be written.
    """
    config = AppConfig()
    yaml_data = config.model_dump()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

    logger.info("Default configuration saved to %s", output_path)
