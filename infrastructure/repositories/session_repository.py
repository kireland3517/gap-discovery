"""
Repository for research session persistence.
"""

from typing import Optional
import json
import logging
from datetime import datetime

from ..database import DatabaseConnection

logger = logging.getLogger(__name__)


class SessionRepository:
    """
    Repository for persisting research session state.

    Stores session data including state machine state, progress,
    and configuration for session recovery.
    """

    def ensure_table_exists(self) -> None:
        """Create the sessions table if it doesn't exist."""
        with DatabaseConnection.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS research_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    state TEXT NOT NULL DEFAULT 'planning',
                    topic TEXT,
                    keywords TEXT,
                    platforms TEXT,
                    posts_collected INTEGER DEFAULT 0,
                    evidence_extracted INTEGER DEFAULT 0,
                    themes_synthesized INTEGER DEFAULT 0,
                    clusters_identified INTEGER DEFAULT 0,
                    errors TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create index for faster lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_session_id
                ON research_sessions(session_id)
            """)

    def save(self, session_data: dict) -> bool:
        """
        Save or update a session.

        Args:
            session_data: Dictionary with session fields including session_id
        """
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()

                # Check if session exists
                cursor.execute(
                    "SELECT id FROM research_sessions WHERE session_id = ?",
                    (session_data["session_id"],)
                )
                existing = cursor.fetchone()

                if existing:
                    # Update existing session
                    cursor.execute("""
                        UPDATE research_sessions SET
                            state = ?,
                            topic = ?,
                            keywords = ?,
                            platforms = ?,
                            posts_collected = ?,
                            evidence_extracted = ?,
                            themes_synthesized = ?,
                            clusters_identified = ?,
                            errors = ?,
                            started_at = ?,
                            completed_at = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE session_id = ?
                    """, (
                        session_data.get("state", "planning"),
                        session_data.get("topic", ""),
                        json.dumps(session_data.get("keywords", [])),
                        json.dumps(session_data.get("platforms", [])),
                        session_data.get("posts_collected", 0),
                        session_data.get("evidence_extracted", 0),
                        session_data.get("themes_synthesized", 0),
                        session_data.get("clusters_identified", 0),
                        json.dumps(session_data.get("errors", [])),
                        session_data.get("started_at"),
                        session_data.get("completed_at"),
                        session_data["session_id"]
                    ))
                else:
                    # Insert new session
                    cursor.execute("""
                        INSERT INTO research_sessions (
                            session_id, state, topic, keywords, platforms,
                            posts_collected, evidence_extracted,
                            themes_synthesized, clusters_identified,
                            errors, started_at, completed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        session_data["session_id"],
                        session_data.get("state", "planning"),
                        session_data.get("topic", ""),
                        json.dumps(session_data.get("keywords", [])),
                        json.dumps(session_data.get("platforms", [])),
                        session_data.get("posts_collected", 0),
                        session_data.get("evidence_extracted", 0),
                        session_data.get("themes_synthesized", 0),
                        session_data.get("clusters_identified", 0),
                        json.dumps(session_data.get("errors", [])),
                        session_data.get("started_at"),
                        session_data.get("completed_at")
                    ))

                return True

        except Exception as e:
            logger.error(f"Error saving session: {e}")
            return False

    def get_by_id(self, session_id: str) -> Optional[dict]:
        """Get a session by its ID."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT session_id, state, topic, keywords, platforms,
                       posts_collected, evidence_extracted,
                       themes_synthesized, clusters_identified,
                       errors, started_at, completed_at,
                       created_at, updated_at
                FROM research_sessions
                WHERE session_id = ?
            """, (session_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None

    def get_recent(self, limit: int = 10) -> list[dict]:
        """Get recent sessions."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT session_id, state, topic, keywords, platforms,
                       posts_collected, evidence_extracted,
                       themes_synthesized, clusters_identified,
                       errors, started_at, completed_at,
                       created_at, updated_at
                FROM research_sessions
                ORDER BY updated_at DESC
                LIMIT ?
            """, (limit,))

            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_active(self) -> list[dict]:
        """Get all active (non-terminal) sessions."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT session_id, state, topic, keywords, platforms,
                       posts_collected, evidence_extracted,
                       themes_synthesized, clusters_identified,
                       errors, started_at, completed_at,
                       created_at, updated_at
                FROM research_sessions
                WHERE state NOT IN ('completed', 'failed', 'cancelled')
                ORDER BY updated_at DESC
            """)

            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def delete(self, session_id: str) -> bool:
        """Delete a session."""
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM research_sessions WHERE session_id = ?",
                    (session_id,)
                )
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return False

    def _row_to_dict(self, row) -> dict:
        """Convert a database row to a dictionary."""
        return {
            "session_id": row["session_id"],
            "state": row["state"],
            "topic": row["topic"],
            "keywords": json.loads(row["keywords"]) if row["keywords"] else [],
            "platforms": json.loads(row["platforms"]) if row["platforms"] else [],
            "posts_collected": row["posts_collected"],
            "evidence_extracted": row["evidence_extracted"],
            "themes_synthesized": row["themes_synthesized"],
            "clusters_identified": row["clusters_identified"],
            "errors": json.loads(row["errors"]) if row["errors"] else [],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
