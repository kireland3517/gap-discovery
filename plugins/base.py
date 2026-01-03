"""
Base classes for scraper plugins.

Defines the interface that all scraper plugins must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class ScraperType(Enum):
    """Types of scrapers."""
    SOCIAL = "social"           # Reddit, Twitter, etc.
    VIDEO = "video"             # YouTube
    FORUM = "forum"             # HackerNews, community forums
    REVIEW = "review"           # G2, Capterra, Trustpilot
    APP_STORE = "app_store"     # App Store, Play Store
    SEARCH = "search"           # Google autocomplete, PAA
    JOB = "job"                 # LinkedIn, Indeed


@dataclass
class ScraperConfig:
    """Configuration for a scraper run."""
    topic: str = ""
    keywords: list[str] = field(default_factory=list)
    max_results: int = 50
    delay_min: float = 1.0
    delay_max: float = 3.0

    # Platform-specific options
    extra: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self.extra.get(key, default)


@dataclass
class ScraperResult:
    """Result from a scraper run."""
    success: bool = True
    posts: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def add_post(self, post: dict) -> None:
        """Add a post to the results."""
        self.posts.append(post)

    def add_error(self, error: str) -> None:
        """Record an error."""
        self.errors.append(error)
        self.success = False

    def complete(self) -> None:
        """Mark the scraper run as complete."""
        self.completed_at = datetime.now()
        self.metrics["duration_seconds"] = (
            self.completed_at - self.started_at
        ).total_seconds()
        self.metrics["posts_collected"] = len(self.posts)
        self.metrics["error_count"] = len(self.errors)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "posts_count": len(self.posts),
            "errors": self.errors,
            "metrics": self.metrics,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ScraperPlugin(ABC):
    """
    Abstract base class for scraper plugins.

    All scrapers must implement this interface to be registered
    and used by the pipeline.
    """

    def __init__(self):
        """Initialize the plugin."""
        self._enabled = True

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique name for this scraper.

        Example: "reddit", "g2_reviews", "google_autocomplete"
        """
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """
        Human-readable display name.

        Example: "Reddit", "G2 Reviews", "Google Autocomplete"
        """
        pass

    @property
    @abstractmethod
    def platform(self) -> str:
        """
        Platform identifier.

        Example: "reddit.com", "g2.com", "google.com"
        """
        pass

    @property
    @abstractmethod
    def scraper_type(self) -> ScraperType:
        """
        Type of scraper.

        Helps categorize scrapers for organization and filtering.
        """
        pass

    @property
    def enabled(self) -> bool:
        """Whether this scraper is enabled."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """Enable or disable this scraper."""
        self._enabled = value

    @abstractmethod
    def can_handle(self, source_type: str) -> bool:
        """
        Check if this scraper can handle the given source type.

        Args:
            source_type: The type of source to check

        Returns:
            True if this scraper can handle the source
        """
        pass

    @abstractmethod
    async def scrape(self, config: ScraperConfig) -> ScraperResult:
        """
        Execute the scraping operation.

        Args:
            config: Configuration for this scrape run

        Returns:
            ScraperResult with collected posts and metrics
        """
        pass

    async def initialize(self) -> None:
        """
        Initialize resources needed for scraping.

        Override this to set up browser, API clients, etc.
        Called before scrape().
        """
        pass

    async def cleanup(self) -> None:
        """
        Clean up resources after scraping.

        Override this to close browser, connections, etc.
        Called after scrape().
        """
        pass

    def validate_config(self, config: ScraperConfig) -> list[str]:
        """
        Validate the configuration for this scraper.

        Override to add custom validation.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        if not config.topic and not config.keywords:
            errors.append("Either topic or keywords required")
        return errors

    def get_info(self) -> dict:
        """Get information about this plugin."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "platform": self.platform,
            "type": self.scraper_type.value,
            "enabled": self.enabled,
        }

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, enabled={self.enabled})"
