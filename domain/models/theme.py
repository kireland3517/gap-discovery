"""
Theme and pattern domain models.

Represents synthesized themes and patterns from pain analysis.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Theme:
    """
    A synthesized theme from pain evidence analysis.

    Themes represent recurring patterns of pain or frustration
    identified across multiple posts.
    """
    id: Optional[int] = None
    topic_id: Optional[int] = None

    # Theme content
    name: str = ""
    description: str = ""
    summary: str = ""

    # Supporting evidence
    supporting_quotes: list[str] = field(default_factory=list)
    post_ids: list[int] = field(default_factory=list)
    evidence_count: int = 0

    # Classification
    category: str = ""  # Main category (workflow, tool, process, etc.)
    subcategory: str = ""

    # Scoring
    confidence_score: float = 0.0
    prevalence_score: float = 0.0  # How common is this theme?
    intensity_score: float = 0.0   # How intense is the pain?

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    validated: bool = False
    validated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "name": self.name,
            "description": self.description,
            "summary": self.summary,
            "supporting_quotes": self.supporting_quotes,
            "post_ids": self.post_ids,
            "evidence_count": self.evidence_count,
            "category": self.category,
            "subcategory": self.subcategory,
            "confidence_score": self.confidence_score,
            "prevalence_score": self.prevalence_score,
            "intensity_score": self.intensity_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "validated": self.validated,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Theme':
        """Create Theme from a dictionary."""
        return cls(
            id=data.get("id"),
            topic_id=data.get("topic_id"),
            name=data.get("name", data.get("theme", "")),
            description=data.get("description", ""),
            summary=data.get("summary", ""),
            supporting_quotes=data.get("supporting_quotes", data.get("quotes", [])),
            post_ids=data.get("post_ids", []),
            evidence_count=data.get("evidence_count", data.get("post_count", 0)),
            category=data.get("category", ""),
            subcategory=data.get("subcategory", ""),
            confidence_score=data.get("confidence_score", data.get("confidence", 0.0)),
            prevalence_score=data.get("prevalence_score", 0.0),
            intensity_score=data.get("intensity_score", 0.0),
            validated=data.get("validated", False),
        )


@dataclass
class Pattern:
    """
    A high-level pattern derived from multiple themes and clusters.

    Patterns represent the most significant pain points that may
    indicate product opportunities.
    """
    id: Optional[int] = None
    topic_id: Optional[int] = None

    # Pattern identification
    name: str = ""
    description: str = ""

    # Related themes and clusters
    theme_ids: list[int] = field(default_factory=list)
    cluster_ids: list[int] = field(default_factory=list)

    # Aggregated insights
    affected_industries: list[str] = field(default_factory=list)
    failed_solutions: list[str] = field(default_factory=list)
    ideal_state_quotes: list[str] = field(default_factory=list)

    # Opportunity assessment
    market_size_indicator: str = ""  # small, medium, large
    urgency_indicator: str = ""      # low, medium, high
    existing_solutions: list[str] = field(default_factory=list)
    solution_gaps: list[str] = field(default_factory=list)

    # Scoring
    opportunity_score: float = 0.0
    confidence_score: float = 0.0
    priority_rank: int = 0

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "name": self.name,
            "description": self.description,
            "theme_ids": self.theme_ids,
            "cluster_ids": self.cluster_ids,
            "affected_industries": self.affected_industries,
            "failed_solutions": self.failed_solutions,
            "ideal_state_quotes": self.ideal_state_quotes,
            "market_size_indicator": self.market_size_indicator,
            "urgency_indicator": self.urgency_indicator,
            "existing_solutions": self.existing_solutions,
            "solution_gaps": self.solution_gaps,
            "opportunity_score": self.opportunity_score,
            "confidence_score": self.confidence_score,
            "priority_rank": self.priority_rank,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Pattern':
        """Create Pattern from a dictionary."""
        return cls(
            id=data.get("id"),
            topic_id=data.get("topic_id"),
            name=data.get("name", ""),
            description=data.get("description", ""),
            theme_ids=data.get("theme_ids", []),
            cluster_ids=data.get("cluster_ids", []),
            affected_industries=data.get("affected_industries", []),
            failed_solutions=data.get("failed_solutions", []),
            ideal_state_quotes=data.get("ideal_state_quotes", []),
            market_size_indicator=data.get("market_size_indicator", ""),
            urgency_indicator=data.get("urgency_indicator", ""),
            existing_solutions=data.get("existing_solutions", []),
            solution_gaps=data.get("solution_gaps", []),
            opportunity_score=data.get("opportunity_score", 0.0),
            confidence_score=data.get("confidence_score", 0.0),
            priority_rank=data.get("priority_rank", 0),
        )
