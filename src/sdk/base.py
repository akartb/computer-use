"""
Base plugin class and plugin lifecycle definitions for Computer Use Plugin.

All plugins must extend BasePlugin and implement the required lifecycle methods.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BasePlugin(ABC):
    """
    Abstract base class for all Computer Use plugins.

    Defines the lifecycle interface that every plugin must implement.
    Plugins are discovered, loaded, configured, and torn down through these methods.

    Attributes:
        _config: Plugin-specific configuration dictionary.
        _initialized: Whether the plugin has been initialized.
    """

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._initialized: bool = False

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Return the unique identifier name of this plugin.

        Returns:
            String identifier, e.g. 'screen-mss', 'input-pyautogui'.
        """
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """
        Return the semantic version of this plugin.

        Returns:
            Version string, e.g. '1.0.0'.
        """
        ...

    @property
    def description(self) -> str:
        """
        Return a human-readable description of this plugin.

        Returns:
            Description string. Defaults to empty string.
        """
        return ""

    @property
    def initialized(self) -> bool:
        """
        Return whether this plugin has been initialized.

        Returns:
            True if initialize() has been called successfully.
        """
        return self._initialized

    @abstractmethod
    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the plugin with the provided configuration.

        Called once after the plugin is loaded. Use this to set up resources,
        validate configuration, and prepare for operation.

        Args:
            config: Plugin-specific configuration dictionary.

        Raises:
            PluginInitError: If initialization fails.
        """
        ...

    async def teardown(self) -> None:
        """
        Clean up resources when the plugin is unloaded.

        Called once before the plugin is removed. Override this to release
        file handles, network connections, or other resources.
        """
        self._initialized = False

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate and normalize the plugin configuration.

        Override this to add plugin-specific config validation.
        Return the validated/normalized config dict.

        Args:
            config: Raw configuration dictionary.

        Returns:
            Validated configuration dictionary.

        Raises:
            ValueError: If configuration is invalid.
        """
        return config


class PluginInitError(Exception):
    """
    Raised when a plugin fails to initialize.

    Attributes:
        plugin_name: Name of the plugin that failed.
        reason: Description of the failure.
    """

    def __init__(self, plugin_name: str, reason: str) -> None:
        self.plugin_name = plugin_name
        self.reason = reason
        super().__init__(f"Plugin '{plugin_name}' initialization failed: {reason}")
