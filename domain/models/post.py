"""
Post domain models.

Represents posts collected from various platforms at different stages
of the processing pipeline.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class PostSource(Enum):
    """Source platforms for posts."""
    REDDIT = "reddit"
    YOUTUBE = "youtube"
    HACKERNEWS = "hackernews"
    QUORA = "quora"
    TWITTER = "twitter"
    G2 = "g2"
    CAPTERRA = "capterra"
    TRUSTPILOT = "trustpilot"
    APP_STORE = "app_store"
    PLAY_STORE = "play_store"
    ZAPIER_COMMUNITY = "zapier_community"
    MAKE_COMMUNITY = "make_community"
    HUBSPOT_COMMUNITY = "hubspot_community"
    UNKNOWN = "unknown"


@dataclass
class Post:
    """Base post model with common fields."""
    id: Optional[int] = None
    source: str = ""
    url: str = ""
    title: str = ""
    content: str = ""
    author: str = ""
    created_at: Optional[datetime] = None

    def get_source_enum(self) -> PostSource:
        """Get the source as an enum value."""
        try:
            return PostSource(self.source.lower())
        except ValueError:
            return PostSource.UNKNOWN


@dataclass
class RawPost(Post):
    """
    Raw post as collected from scraping.

    Contains original data before any processing.
    """
    topic_id: Optional[int] = None
    keyword_id: Optional[int] = None
    upvotes: int = 0
    comments: int = 0
    date_posted: Optional[str] = None
    scraped_at: datetime = field(default_factory=datetime.now)

    # Scraping metadata
    scraper_version: str = ""
    raw_html: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "keyword_id": self.keyword_id,
            "source": self.source,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "upvotes": self.upvotes,
            "comments": self.comments,
            "date_posted": self.date_posted,
            "scraped_at": self.scraped_at.isoformat() if self.scraped_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'RawPost':
        """Create a RawPost from a dictionary."""
        return cls(
            id=data.get("id"),
            topic_id=data.get("topic_id"),
            keyword_id=data.get("keyword_id"),
            source=data.get("source", ""),
            url=data.get("url", ""),
            title=data.get("title", ""),
            content=data.get("content", ""),
            author=data.get("author", ""),
            upvotes=data.get("upvotes", 0),
            comments=data.get("comments", 0),
            date_posted=data.get("date_posted"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        )


@dataclass
class ProcessedPost(Post):
    """
    Post after processing and validation.

    Contains analysis results and quality scores.
    """
    topic_id: Optional[int] = None
    processed: bool = False
    processed_at: Optional[datetime] = None

    # Complaint detection
    is_complaint: bool = False
    complaint_confidence: float = 0.0

    # Quality metrics
    quality_score: float = 0.0
    relevance_score: float = 0.0

    # Extracted metadata
    detected_industry: str = ""
    detected_emotion: str = ""
    detected_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic_id": self.topic_id,
            "source": self.source,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "processed": self.processed,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "is_complaint": self.is_complaint,
            "complaint_confidence": self.complaint_confidence,
            "quality_score": self.quality_score,
            "relevance_score": self.relevance_score,
            "detected_industry": self.detected_industry,
            "detected_emotion": self.detected_emotion,
            "detected_tools": self.detected_tools,
        }

    @classmethod
    def from_raw_post(cls, raw: RawPost, **kwargs) -> 'ProcessedPost':
        """Create a ProcessedPost from a RawPost."""
        return cls(
            id=raw.id,
            topic_id=raw.topic_id,
            source=raw.source,
            url=raw.url,
            title=raw.title,
            content=raw.content,
            author=raw.author,
            created_at=raw.created_at,
            **kwargs
        )
