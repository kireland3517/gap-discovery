"""
Repository for post data access.
"""

from typing import Optional
import logging

from ..database import DatabaseConnection
from domain.models import RawPost, ProcessedPost

logger = logging.getLogger(__name__)


class PostRepository:
    """Repository for accessing and storing posts."""

    def get_by_id(self, post_id: int) -> Optional[RawPost]:
        """Get a post by ID."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT id, topic_id, keyword_id, source, url, title, content,
                       author, upvotes, comments, date_posted, created_at
                FROM posts
                WHERE id = ?
            """, (post_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_raw_post(row)
            return None

    def get_unprocessed(self, topic_id: Optional[int] = None, limit: int = 100) -> list[RawPost]:
        """Get unprocessed posts, optionally filtered by topic."""
        with DatabaseConnection.cursor() as cursor:
            if topic_id:
                cursor.execute("""
                    SELECT id, topic_id, keyword_id, source, url, title, content,
                           author, upvotes, comments, date_posted, created_at
                    FROM posts
                    WHERE processed = 0 AND topic_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (topic_id, limit))
            else:
                cursor.execute("""
                    SELECT id, topic_id, keyword_id, source, url, title, content,
                           author, upvotes, comments, date_posted, created_at
                    FROM posts
                    WHERE processed = 0
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))

            return [self._row_to_raw_post(row) for row in cursor.fetchall()]

    def get_by_topic(self, topic_id: int, limit: int = 100) -> list[RawPost]:
        """Get posts for a specific topic."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT id, topic_id, keyword_id, source, url, title, content,
                       author, upvotes, comments, date_posted, created_at
                FROM posts
                WHERE topic_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (topic_id, limit))

            return [self._row_to_raw_post(row) for row in cursor.fetchall()]

    def add(self, post: RawPost) -> Optional[int]:
        """Add a new post. Returns the new post ID or None if duplicate."""
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO posts (topic_id, keyword_id, source, url, title,
                                       content, author, upvotes, comments, date_posted)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    post.topic_id, post.keyword_id, post.source, post.url,
                    post.title, post.content, post.author, post.upvotes,
                    post.comments, post.date_posted
                ))
                return cursor.lastrowid
        except Exception as e:
            if "UNIQUE constraint" in str(e):
                return None
            logger.error(f"Error adding post: {e}")
            raise

    def mark_processed(self, post_id: int) -> bool:
        """Mark a post as processed."""
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE posts SET processed = 1 WHERE id = ?
                """, (post_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error marking post processed: {e}")
            return False

    def count_by_source(self, topic_id: Optional[int] = None) -> dict[str, int]:
        """Get post counts grouped by source."""
        with DatabaseConnection.cursor() as cursor:
            if topic_id:
                cursor.execute("""
                    SELECT source, COUNT(*) as count
                    FROM posts
                    WHERE topic_id = ?
                    GROUP BY source
                """, (topic_id,))
            else:
                cursor.execute("""
                    SELECT source, COUNT(*) as count
                    FROM posts
                    GROUP BY source
                """)

            return {row["source"]: row["count"] for row in cursor.fetchall()}

    def _row_to_raw_post(self, row) -> RawPost:
        """Convert a database row to a RawPost."""
        return RawPost(
            id=row["id"],
            topic_id=row["topic_id"],
            keyword_id=row["keyword_id"],
            source=row["source"],
            url=row["url"],
            title=row["title"],
            content=row["content"],
            author=row["author"],
            upvotes=row["upvotes"],
            comments=row["comments"],
            date_posted=row["date_posted"],
        )
