"""
Pain point domain models.

Represents pain evidence and clusters identified during analysis.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class QuestionType(Enum):
    """The four questions framework for pain classification."""
    MANUAL_TASK = "manual_task"          # What manual task is causing frustration?
    COST_IMPACT = "cost_impact"          # What does it cost them?
    FAILED_SOLUTIONS = "failed_solutions" # What have they tried that failed?
    IDEAL_STATE = "ideal_state"          # What would "better" look like?


class HumanLens(Enum):
    """Human-centered lens tags for pain evidence."""
    TRUST_ISSUE = "trust_issue"           # People don't rely on the system
    COGNITIVE_LOAD = "cognitive_load"     # Too many steps or mental overhead
    CHANGE_RESISTANCE = "change_resistance" # Process changes cause failure
    ERROR_SENSITIVITY = "error_sensitivity" # Mistakes are costly
    EMOTIONAL_STAKES = "emotional_stakes" # Involves clients, money, compliance


class Emotion(Enum):
    """Detected emotional state."""
    FRUSTRATED = "frustrated"
    OVERWHELMED = "overwhelmed"
    ANXIOUS = "anxious"
    RESIGNED = "resigned"
    NEUTRAL = "neutral"


class Industry(Enum):
    """Detected industry context."""
    FREELANCE = "freelance"
    AGENCY = "agency"
    ECOMMERCE = "ecommerce"
    SAAS = "saas"
    CONSULTING = "consulting"
    HEALTHCARE = "healthcare"
    REAL_ESTATE = "real_estate"
    OTHER = "other"


@dataclass
class PainEvidence:
    """
    A single piece of pain evidence extracted from a post.

    Each evidence entry answers at least one of the four questions
    and includes the verbatim quote from the user.
    """
    id: Optional[int] = None
    post_id: Optional[int] = None
    topic_id: Optional[int] = None

    # The verbatim quote (never paraphrased)
    verbatim_quote: str = ""

    # Classification
    question_type: str = ""  # QuestionType value
    human_lenses: list[str] = field(default_factory=list)  # HumanLens values

    # Context
    industry: str = ""  # Industry value
    emotion: str = ""   # Emotion value
    source_url: str = ""

    # Quality scoring
    quality_score: float = 0.0
    flagged_for_removal: bool = False
    removal_reason: str = ""

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "post_id": self.post_id,
            "topic_id": self.topic_id,
            "verbatim_quote": self.verbatim_quote,
            "question_type": self.question_type,
            "human_lenses": self.human_lenses,
            "industry": self.industry,
            "emotion": self.emotion,
            "source_url": self.source_url,
            "quality_score": self.quality_score,
            "flagged_for_removal": self.flagged_for_removal,
            "removal_reason": self.removal_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PainEvidence':
        """Create PainEvidence from a dictionary."""
        return cls(
            id=data.get("id"),
            post_id=data.get("post_id"),
            topic_id=data.get("topic_id"),
            verbatim_quote=data.get("verbatim_quote", data.get("quote", "")),
            question_type=data.get("question_type", ""),
            human_lenses=data.get("human_lenses", data.get("lenses", [])),
            industry=data.get("industry", ""),
            emotion=data.get("emotion", ""),
            source_url=data.get("source_url", ""),
            quality_score=data.get("quality_score", 0.0),
            flagged_for_removal=data.get("flagged_for_removal", False),
            removal_reason=data.get("removal_reason", ""),
        )

    def get_question_type_enum(self) -> Optional[QuestionType]:
        """Get the question type as an enum value."""
        try:
            return QuestionType(self.question_type.lower())
        except ValueError:
            return None


@dataclass
class PainCluster:
    """
    A cluster of related pain evidence.

    Created when 3+ evidence entries share the same underlying pain.
    """
    id: Optional[int] = None
    topic_id: Optional[int] = None

    # Cluster identification
    name: str = ""
    description: str = ""

    # Evidence in this cluster
    evidence_ids: list[int] = field(default_factory=list)
    evidence_count: int = 0

    # Aggregated data
    common_question_types: list[str] = field(default_factory=list)
    common_human_lenses: list[str] = field(default_factory=list)
    common_industries: list[str] = field(default_factory=list)
    common_emotions: list[str] = field(default_factory=list)

    # Failed solutions mentioned across evidence
    failed_solutions: list[str] = field(default_factory=list)

    # Scoring
    strength_score: float = 0.0  # How strong is this pain pattern?
    opportunity_score: float = 0.0  # How good an opportunity is this?

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "name": self.name,
            "description": self.description,
            "evidence_ids": self.evidence_ids,
            "evidence_count": self.evidence_count,
            "common_question_types": self.common_question_types,
            "common_human_lenses": self.common_human_lenses,
            "common_industries": self.common_industries,
            "common_emotions": self.common_emotions,
            "failed_solutions": self.failed_solutions,
            "strength_score": self.strength_score,
            "opportunity_score": self.opportunity_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PainCluster':
        """Create PainCluster from a dictionary."""
        return cls(
            id=data.get("id"),
            topic_id=data.get("topic_id"),
            name=data.get("name", data.get("cluster_name", "")),
            description=data.get("description", ""),
            evidence_ids=data.get("evidence_ids", []),
            evidence_count=data.get("evidence_count", len(data.get("evidence_ids", []))),
            common_question_types=data.get("common_question_types", []),
            common_human_lenses=data.get("common_human_lenses", []),
            common_industries=data.get("common_industries", []),
            common_emotions=data.get("common_emotions", []),
            failed_solutions=data.get("failed_solutions", []),
            strength_score=data.get("strength_score", 0.0),
            opportunity_score=data.get("opportunity_score", 0.0),
        )
