"""
Plugin architecture for extensible scrapers.

Provides a plugin interface and registry for dynamically loading scrapers.
"""

from .base import ScraperPlugin, ScraperConfig, ScraperResult
from .registry import PluginRegistry

__all__ = [
    'ScraperPlugin',
    'ScraperConfig',
    'ScraperResult',
    'PluginRegistry',
]
