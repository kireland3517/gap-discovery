"""
Pipeline context for passing data between stages.

The context acts as a shared state container that flows through the pipeline.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from enum import Enum


class ResearchPhase(Enum):
    """Current phase of the research pipeline."""
    INITIALIZED = "initialized"
    SCRAPING = "scraping"
    VALIDATING = "validating"
    SYNTHESIZING = "synthesizing"
    CLUSTERING = "clustering"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ResearchConfig:
    """Configuration for a research session."""
    topic: str
    keywords: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    max_posts_per_platform: int = 50
    enable_pain_validation: bool = True
    enable_synthesis: bool = True
    enable_clustering: bool = True

    # API settings
    api_cost_limit_usd: float = 10.0
    max_api_failures: int = 5

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "keywords": self.keywords,
            "platforms": self.platforms,
            "max_posts_per_platform": self.max_posts_per_platform,
            "enable_pain_validation": self.enable_pain_validation,
            "enable_synthesis": self.enable_synthesis,
            "enable_clustering": self.enable_clustering,
            "api_cost_limit_usd": self.api_cost_limit_usd,
            "max_api_failures": self.max_api_failures,
        }


@dataclass
class PipelineContext:
    """
    Shared context that flows through the pipeline.

    Holds:
    - Research configuration
    - Data collected at each stage
    - Metrics and statistics
    - Error tracking
    """

    # Configuration
    config: ResearchConfig
    session_id: str = ""

    # Current state
    phase: ResearchPhase = ResearchPhase.INITIALIZED
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # Stage data - populated as pipeline progresses
    raw_posts: list[dict] = field(default_factory=list)
    validated_evidence: list[dict] = field(default_factory=list)
    synthesized_themes: list[dict] = field(default_factory=list)
    clustered_patterns: list[dict] = field(default_factory=list)

    # Metrics
    metrics: dict = field(default_factory=dict)

    # Errors
    errors: list[dict] = field(default_factory=list)

    def add_error(self, stage: str, error: Exception, context: Optional[dict] = None) -> None:
        """Record an error that occurred during processing."""
        self.errors.append({
            "stage": stage,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "timestamp": datetime.now().isoformat(),
            "context": context or {}
        })

    def update_metric(self, key: str, value: Any) -> None:
        """Update a metric value."""
        self.metrics[key] = value

    def increment_metric(self, key: str, amount: int = 1) -> None:
        """Increment a numeric metric."""
        current = self.metrics.get(key, 0)
        self.metrics[key] = current + amount

    def get_duration_seconds(self) -> float:
        """Get elapsed time in seconds."""
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()

    def mark_completed(self) -> None:
        """Mark the pipeline as completed."""
        self.phase = ResearchPhase.COMPLETED
        self.completed_at = datetime.now()

    def mark_failed(self) -> None:
        """Mark the pipeline as failed."""
        self.phase = ResearchPhase.FAILED
        self.completed_at = datetime.now()

    def to_dict(self) -> dict:
        """Convert context to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "config": self.config.to_dict(),
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "raw_posts_count": len(self.raw_posts),
            "validated_evidence_count": len(self.validated_evidence),
            "synthesized_themes_count": len(self.synthesized_themes),
            "clustered_patterns_count": len(self.clustered_patterns),
            "metrics": self.metrics,
            "errors": self.errors,
            "duration_seconds": self.get_duration_seconds(),
        }

    def get_summary(self) -> str:
        """Get a human-readable summary of the context state."""
        return (
            f"Research Session: {self.session_id or 'unnamed'}\n"
            f"  Topic: {self.config.topic}\n"
            f"  Phase: {self.phase.value}\n"
            f"  Posts: {len(self.raw_posts)}\n"
            f"  Evidence: {len(self.validated_evidence)}\n"
            f"  Themes: {len(self.synthesized_themes)}\n"
            f"  Patterns: {len(self.clustered_patterns)}\n"
            f"  Errors: {len(self.errors)}\n"
            f"  Duration: {self.get_duration_seconds():.1f}s"
        )
