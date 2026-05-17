"""
Plugin Manager for Computer Use Plugin.

Discovers, loads, configures, and manages plugin lifecycle.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any

import pluggy

from src.sdk.base import BasePlugin, PluginInitError
from src.sdk.hooks import ComputerUseHookSpec

logger = logging.getLogger(__name__)


class PluginInfo:
    """
    Descriptor for a discovered but not yet loaded plugin.

    Attributes:
        name: Plugin identifier.
        module_path: Python module path or file path.
        plugin_class: The plugin class (set after import).
        version: Plugin version string.
        description: Human-readable description.
    """

    def __init__(
        self,
        name: str,
        module_path: str,
        plugin_class: type[BasePlugin] | None = None,
        version: str = "",
        description: str = "",
    ) -> None:
        self.name = name
        self.module_path = module_path
        self.plugin_class = plugin_class
        self.version = version
        self.description = description

    def __repr__(self) -> str:
        return f"PluginInfo(name={self.name!r}, version={self.version!r})"


class PluginManager:
    """
    Manages plugin lifecycle: discovery, loading, configuration, and teardown.

    Uses pluggy for hook specification and implementation. Plugins are discovered
    from configured directories, loaded on demand, and isolated from each other.

    Attributes:
        _pm: pluggy PluginManager instance.
        _plugins: Dict of loaded plugin instances keyed by name.
        _plugin_infos: Dict of discovered PluginInfo objects keyed by name.
        _config: Global configuration dictionary.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._pm = pluggy.PluginManager("computer_use")
        self._pm.add_hookspecs(ComputerUseHookSpec)
        self._plugins: dict[str, BasePlugin] = {}
        self._plugin_infos: dict[str, PluginInfo] = {}
        self._config: dict[str, Any] = config or {}

    @property
    def hook(self) -> Any:
        """
        Return the pluggy hook namespace for calling registered hooks.

        Returns:
            The hook namespace object with methods matching ComputerUseHookSpec.
        """
        return self._pm.hook

    def discover_plugins(self, plugin_dirs: list[str | Path] | None = None) -> list[PluginInfo]:
        """
        Scan directories for valid plugin modules.

        Looks for Python modules that contain a class extending BasePlugin.
        Default scan directories are src/plugins/*.

        Args:
            plugin_dirs: List of directory paths to scan. Defaults to built-in plugin dirs.

        Returns:
            List of PluginInfo objects describing discovered plugins.
        """
        if plugin_dirs is None:
            base_dir = Path(__file__).parent.parent / "plugins"
            plugin_dirs = [d for d in base_dir.iterdir() if d.is_dir() and (d / "__init__.py").exists()]

        discovered: list[PluginInfo] = []

        for dir_path in plugin_dirs:
            dir_path = Path(dir_path)
            if not dir_path.exists():
                logger.warning("Plugin directory does not exist: %s", dir_path)
                continue

            for item in dir_path.iterdir():
                if item.is_file() and item.suffix == ".py" and item.stem != "__init__":
                    info = self._inspect_module(item)
                    if info is not None:
                        self._plugin_infos[info.name] = info
                        discovered.append(info)
                elif item.is_dir() and (item / "__init__.py").exists():
                    info = self._inspect_package(item)
                    if info is not None:
                        self._plugin_infos[info.name] = info
                        discovered.append(info)

        logger.info("Discovered %d plugins: %s", len(discovered), [p.name for p in discovered])
        return discovered

    def _inspect_module(self, path: Path) -> PluginInfo | None:
        """
        Inspect a Python module file for a BasePlugin subclass.

        Args:
            path: Path to the .py file.

        Returns:
            PluginInfo if a valid plugin class is found, else None.
        """
        try:
            module_name = f"plugins.{path.parent.stem}.{path.stem}"
            if module_name not in sys.modules:
                spec = importlib.util.spec_from_file_location(module_name, str(path))
                if spec is None or spec.loader is None:
                    return None
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            else:
                module = sys.modules[module_name]

            return self._find_plugin_class(module, str(path))
        except Exception as e:
            logger.warning("Failed to inspect module %s: %s", path, e)
            return None

    def _inspect_package(self, path: Path) -> PluginInfo | None:
        """
        Inspect a Python package directory for a BasePlugin subclass.

        Args:
            path: Path to the package directory.

        Returns:
            PluginInfo if a valid plugin class is found, else None.
        """
        try:
            module_name = f"plugins.{path.stem}"
            if module_name not in sys.modules:
                spec = importlib.util.spec_from_file_location(
                    module_name, str(path / "__init__.py"),
                    submodule_search_locations=[str(path)],
                )
                if spec is None or spec.loader is None:
                    return None
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            else:
                module = sys.modules[module_name]

            return self._find_plugin_class(module, str(path))
        except Exception as e:
            logger.warning("Failed to inspect package %s: %s", path, e)
            return None

    def _find_plugin_class(self, module: Any, module_path: str) -> PluginInfo | None:
        """
        Search a module for a concrete BasePlugin subclass.

        Args:
            module: The imported Python module.
            module_path: File path for reference.

        Returns:
            PluginInfo if found, else None.
        """
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, BasePlugin)
                and attr is not BasePlugin
                and not inspect.isabstract(attr)
            ):
                temp_instance = attr()
                return PluginInfo(
                    name=temp_instance.name,
                    module_path=module_path,
                    plugin_class=attr,
                    version=temp_instance.version,
                    description=temp_instance.description,
                )
        return None

    async def load_plugin(self, plugin_name: str, config: dict[str, Any] | None = None) -> BasePlugin:
        """
        Load and initialize a plugin by name.

        Args:
            plugin_name: The unique name of the plugin to load.
            config: Optional plugin-specific configuration override.

        Returns:
            The initialized plugin instance.

        Raises:
            KeyError: If the plugin has not been discovered.
            PluginInitError: If the plugin fails to initialize.
        """
        info = self._plugin_infos.get(plugin_name)
        if info is None:
            raise KeyError(f"Plugin '{plugin_name}' not discovered. Call discover_plugins() first.")
        if info.plugin_class is None:
            raise KeyError(f"Plugin '{plugin_name}' has no class reference.")

        if plugin_name in self._plugins:
            logger.info("Plugin '%s' already loaded", plugin_name)
            return self._plugins[plugin_name]

        plugin = info.plugin_class()
        plugin_config = config or self._config.get("plugins", {}).get(plugin_name, {})
        validated_config = plugin.validate_config(plugin_config)

        try:
            await plugin.initialize(validated_config)
        except Exception as e:
            raise PluginInitError(plugin_name, str(e)) from e

        self._pm.register(plugin, name=plugin_name)
        self._plugins[plugin_name] = plugin
        logger.info("Loaded plugin: %s v%s", plugin_name, plugin.version)
        return plugin

    async def unload_plugin(self, plugin_name: str) -> None:
        """
        Unload and tear down a plugin by name.

        Args:
            plugin_name: The unique name of the plugin to unload.

        Raises:
            KeyError: If the plugin is not currently loaded.
        """
        if plugin_name not in self._plugins:
            raise KeyError(f"Plugin '{plugin_name}' is not loaded.")

        plugin = self._plugins.pop(plugin_name)
        self._pm.unregister(plugin)
        await plugin.teardown()
        logger.info("Unloaded plugin: %s", plugin_name)

    async def load_all(self, config: dict[str, Any] | None = None) -> list[BasePlugin]:
        """
        Load all discovered plugins.

        Args:
            config: Optional configuration override.

        Returns:
            List of all loaded plugin instances.
        """
        loaded: list[BasePlugin] = []
        for name in list(self._plugin_infos.keys()):
            try:
                plugin = await self.load_plugin(name, config)
                loaded.append(plugin)
            except PluginInitError as e:
                logger.error("Failed to load plugin '%s': %s", name, e.reason)
        return loaded

    async def teardown_all(self) -> None:
        """
        Tear down all loaded plugins in reverse load order.
        """
        for name in list(reversed(list(self._plugins.keys()))):
            try:
                await self.unload_plugin(name)
            except Exception as e:
                logger.error("Error tearing down plugin '%s': %s", name, e)

    def get_plugin(self, plugin_name: str) -> BasePlugin | None:
        """
        Get a loaded plugin instance by name.

        Args:
            plugin_name: The plugin name.

        Returns:
            The plugin instance, or None if not loaded.
        """
        return self._plugins.get(plugin_name)

    def list_plugins(self) -> dict[str, dict[str, Any]]:
        """
        List all discovered plugins with their status.

        Returns:
            Dict mapping plugin name to info dict with 'loaded', 'version', 'description'.
        """
        result: dict[str, dict[str, Any]] = {}
        for name, info in self._plugin_infos.items():
            result[name] = {
                "loaded": name in self._plugins,
                "version": info.version,
                "description": info.description,
            }
        return result
