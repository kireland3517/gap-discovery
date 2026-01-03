"""
Research configuration domain model.

Typed configuration for research sessions.
"""

from dataclasses import dataclass, field
from typing import Optional
import yaml
from pathlib import Path


@dataclass
class ScraperConfig:
    """Configuration for a scraper."""
    enabled: bool = True
    max_results: int = 50
    delay_min: float = 1.0
    delay_max: float = 3.0


@dataclass
class APIConfig:
    """Configuration for API usage."""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    cost_limit_usd: float = 10.0
    max_failures: int = 5
    cooldown_seconds: int = 300


@dataclass
class ResearchConfig:
    """
    Typed configuration for a research session.

    Replaces the untyped dict-based configuration with
    validated dataclass fields.
    """
    # Research target
    topic: str = ""
    keywords: list[str] = field(default_factory=list)

    # Platform configuration
    platforms: list[str] = field(default_factory=list)
    max_posts_per_platform: int = 50

    # Processing options
    enable_pain_validation: bool = True
    enable_synthesis: bool = True
    enable_clustering: bool = True
    min_cluster_size: int = 3

    # API configuration
    api: APIConfig = field(default_factory=APIConfig)

    # Scraper configuration
    scraper: ScraperConfig = field(default_factory=ScraperConfig)

    # Pain Intelligence specific
    tools_to_analyze: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary format compatible with existing code."""
        return {
            "topic": self.topic,
            "keywords": self.keywords,
            "platforms": self.platforms,
            "max_posts_per_platform": self.max_posts_per_platform,
            "enable_pain_validation": self.enable_pain_validation,
            "enable_synthesis": self.enable_synthesis,
            "enable_clustering": self.enable_clustering,
            "min_cluster_size": self.min_cluster_size,
            "anthropic": {
                "model": self.api.model,
                "max_tokens": self.api.max_tokens,
            },
            "scraping": {
                "delay_min": self.scraper.delay_min,
                "delay_max": self.scraper.delay_max,
                "max_results": self.scraper.max_results,
            },
            "api_cost_limit_usd": self.api.cost_limit_usd,
            "max_api_failures": self.api.max_failures,
        }

    @classmethod
    def from_yaml(cls, path: str = "config.yaml") -> 'ResearchConfig':
        """Load configuration from YAML file."""
        config_path = Path(path)
        if not config_path.exists():
            return cls()

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> 'ResearchConfig':
        """Create configuration from a dictionary."""
        anthropic_config = data.get("anthropic", {})
        scraping_config = data.get("scraping", {})
        pain_intel = data.get("pain_intelligence", {})

        # Extract topics and keywords from first topic if available
        topics = data.get("topics", [])
        topic = ""
        keywords = []
        if topics:
            first_topic = topics[0]
            topic = first_topic.get("name", "")
            keywords = first_topic.get("keywords", [])

        # Extract tool names for pain intelligence
        tools = pain_intel.get("tool_reviews", {}).get("tools", [])
        tool_names = [t.get("name", "") for t in tools if t.get("name")]

        return cls(
            topic=topic,
            keywords=keywords,
            platforms=data.get("platforms", ["reddit", "youtube", "hackernews"]),
            max_posts_per_platform=scraping_config.get("max_results", 50),
            enable_pain_validation=True,
            enable_synthesis=True,
            enable_clustering=True,
            min_cluster_size=3,
            api=APIConfig(
                model=anthropic_config.get("model", "claude-sonnet-4-20250514"),
                max_tokens=anthropic_config.get("max_tokens", 4096),
                cost_limit_usd=data.get("api_cost_limit_usd", 10.0),
                max_failures=data.get("max_api_failures", 5),
            ),
            scraper=ScraperConfig(
                enabled=True,
                max_results=scraping_config.get("max_results", 50),
                delay_min=scraping_config.get("delay_min", 1.0),
                delay_max=scraping_config.get("delay_max", 3.0),
            ),
            tools_to_analyze=tool_names,
        )

    def validate(self) -> list[str]:
        """Validate the configuration and return list of errors."""
        errors = []

        if not self.topic:
            errors.append("Topic is required")

        if self.max_posts_per_platform < 1:
            errors.append("max_posts_per_platform must be at least 1")

        if self.api.cost_limit_usd <= 0:
            errors.append("API cost limit must be positive")

        if self.min_cluster_size < 2:
            errors.append("min_cluster_size must be at least 2")

        return errors
