"""
Plugin registry for discovering and managing scrapers.

Provides auto-discovery of plugins and runtime management.
"""

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Optional, Type

from .base import ScraperPlugin, ScraperType

logger = logging.getLogger(__name__)


class PluginRegistry:
    """
    Registry for scraper plugins.

    Features:
    - Auto-discovery of plugins in the scrapers directory
    - Manual plugin registration
    - Filtering by type or capability
    - Enable/disable plugins at runtime
    """

    _instance: Optional['PluginRegistry'] = None

    def __init__(self):
        """Initialize the registry."""
        self._plugins: dict[str, ScraperPlugin] = {}
        self._plugin_classes: dict[str, Type[ScraperPlugin]] = {}

    @classmethod
    def get_instance(cls) -> 'PluginRegistry':
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, plugin: ScraperPlugin) -> None:
        """
        Register a plugin instance.

        Args:
            plugin: The plugin to register
        """
        if plugin.name in self._plugins:
            logger.warning(f"Overwriting existing plugin: {plugin.name}")

        self._plugins[plugin.name] = plugin
        logger.info(f"Registered plugin: {plugin.name}")

    def register_class(self, plugin_class: Type[ScraperPlugin]) -> None:
        """
        Register a plugin class (instantiated on first use).

        Args:
            plugin_class: The plugin class to register
        """
        # Create a temporary instance to get the name
        temp = plugin_class()
        name = temp.name

        self._plugin_classes[name] = plugin_class
        logger.info(f"Registered plugin class: {name}")

    def get(self, name: str) -> Optional[ScraperPlugin]:
        """
        Get a plugin by name.

        Args:
            name: The plugin name

        Returns:
            The plugin instance or None if not found
        """
        # Check for existing instance
        if name in self._plugins:
            return self._plugins[name]

        # Check for registered class
        if name in self._plugin_classes:
            plugin = self._plugin_classes[name]()
            self._plugins[name] = plugin
            return plugin

        return None

    def get_all(self) -> list[ScraperPlugin]:
        """Get all registered plugins."""
        # Instantiate any uninstantiated plugin classes
        for name, cls in self._plugin_classes.items():
            if name not in self._plugins:
                self._plugins[name] = cls()

        return list(self._plugins.values())

    def get_enabled(self) -> list[ScraperPlugin]:
        """Get all enabled plugins."""
        return [p for p in self.get_all() if p.enabled]

    def get_by_type(self, scraper_type: ScraperType) -> list[ScraperPlugin]:
        """Get plugins of a specific type."""
        return [p for p in self.get_all() if p.scraper_type == scraper_type]

    def get_by_capability(self, source_type: str) -> list[ScraperPlugin]:
        """Get plugins that can handle a source type."""
        return [p for p in self.get_all() if p.can_handle(source_type)]

    def enable(self, name: str) -> bool:
        """Enable a plugin by name."""
        plugin = self.get(name)
        if plugin:
            plugin.enabled = True
            logger.info(f"Enabled plugin: {name}")
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a plugin by name."""
        plugin = self.get(name)
        if plugin:
            plugin.enabled = False
            logger.info(f"Disabled plugin: {name}")
            return True
        return False

    def discover(self, plugins_path: Optional[Path] = None) -> int:
        """
        Auto-discover plugins in the scrapers directory.

        Args:
            plugins_path: Path to the plugins directory
                         (defaults to plugins/scrapers)

        Returns:
            Number of plugins discovered
        """
        if plugins_path is None:
            plugins_path = Path(__file__).parent / "scrapers"

        if not plugins_path.exists():
            logger.warning(f"Plugins directory not found: {plugins_path}")
            return 0

        count = 0
        for file in plugins_path.glob("*.py"):
            if file.name.startswith("_"):
                continue

            try:
                # Import the module
                spec = importlib.util.spec_from_file_location(
                    f"plugins.scrapers.{file.stem}",
                    file
                )
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                # Find and register ScraperPlugin subclasses
                for name in dir(module):
                    obj = getattr(module, name)
                    if (
                        isinstance(obj, type) and
                        issubclass(obj, ScraperPlugin) and
                        obj is not ScraperPlugin
                    ):
                        try:
                            self.register_class(obj)
                            count += 1
                        except Exception as e:
                            logger.error(f"Failed to register {name}: {e}")

            except Exception as e:
                logger.error(f"Failed to load plugin from {file}: {e}")

        logger.info(f"Discovered {count} plugins in {plugins_path}")
        return count

    def get_info(self) -> dict:
        """Get registry information."""
        plugins = self.get_all()
        return {
            "total_plugins": len(plugins),
            "enabled_plugins": len([p for p in plugins if p.enabled]),
            "plugins": [p.get_info() for p in plugins],
            "by_type": {
                t.value: len([p for p in plugins if p.scraper_type == t])
                for t in ScraperType
            }
        }

    def clear(self) -> None:
        """Clear all registered plugins."""
        self._plugins.clear()
        self._plugin_classes.clear()
        logger.info("Cleared plugin registry")
