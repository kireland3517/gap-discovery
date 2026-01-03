"""
Repository for pain evidence and cluster data access.
"""

from typing import Optional
import json
import logging

from ..database import DatabaseConnection
from domain.models import PainEvidence, PainCluster

logger = logging.getLogger(__name__)


class PainRepository:
    """Repository for accessing and storing pain evidence and clusters."""

    # Pain Evidence methods

    def get_evidence_by_id(self, evidence_id: int) -> Optional[PainEvidence]:
        """Get pain evidence by ID."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT id, post_id, topic_id, verbatim_quote, question_type,
                       human_lenses, industry, emotion, source_url,
                       quality_score, flagged_for_removal, created_at
                FROM pain_evidence
                WHERE id = ?
            """, (evidence_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_evidence(row)
            return None

    def get_evidence_by_topic(self, topic_id: int, limit: int = 100) -> list[PainEvidence]:
        """Get pain evidence for a topic."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT id, post_id, topic_id, verbatim_quote, question_type,
                       human_lenses, industry, emotion, source_url,
                       quality_score, flagged_for_removal, created_at
                FROM pain_evidence
                WHERE topic_id = ? AND flagged_for_removal = 0
                ORDER BY quality_score DESC
                LIMIT ?
            """, (topic_id, limit))

            return [self._row_to_evidence(row) for row in cursor.fetchall()]

    def get_evidence_by_question_type(
        self,
        topic_id: int,
        question_type: str,
        limit: int = 50
    ) -> list[PainEvidence]:
        """Get pain evidence filtered by question type."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT id, post_id, topic_id, verbatim_quote, question_type,
                       human_lenses, industry, emotion, source_url,
                       quality_score, flagged_for_removal, created_at
                FROM pain_evidence
                WHERE topic_id = ? AND question_type = ? AND flagged_for_removal = 0
                ORDER BY quality_score DESC
                LIMIT ?
            """, (topic_id, question_type, limit))

            return [self._row_to_evidence(row) for row in cursor.fetchall()]

    def add_evidence(self, evidence: PainEvidence) -> Optional[int]:
        """Add new pain evidence. Returns the new ID."""
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()

                # Convert lists to JSON
                lenses_json = json.dumps(evidence.human_lenses)

                cursor.execute("""
                    INSERT INTO pain_evidence (post_id, topic_id, verbatim_quote,
                                              question_type, human_lenses, industry,
                                              emotion, source_url, quality_score,
                                              flagged_for_removal)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    evidence.post_id, evidence.topic_id, evidence.verbatim_quote,
                    evidence.question_type, lenses_json, evidence.industry,
                    evidence.emotion, evidence.source_url, evidence.quality_score,
                    evidence.flagged_for_removal
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding pain evidence: {e}")
            raise

    def update_quality_score(self, evidence_id: int, score: float) -> bool:
        """Update the quality score for evidence."""
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE pain_evidence SET quality_score = ? WHERE id = ?
                """, (score, evidence_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error updating quality score: {e}")
            return False

    def flag_for_removal(self, evidence_id: int, reason: str = "") -> bool:
        """Flag evidence for removal."""
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE pain_evidence
                    SET flagged_for_removal = 1
                    WHERE id = ?
                """, (evidence_id,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Error flagging evidence: {e}")
            return False

    # Pain Cluster methods

    def get_cluster_by_id(self, cluster_id: int) -> Optional[PainCluster]:
        """Get pain cluster by ID."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT id, topic_id, name, description, evidence_count,
                       strength_score, opportunity_score, created_at
                FROM pain_clusters
                WHERE id = ?
            """, (cluster_id,))

            row = cursor.fetchone()
            if row:
                return self._row_to_cluster(row)
            return None

    def get_clusters_by_topic(self, topic_id: int, limit: int = 50) -> list[PainCluster]:
        """Get pain clusters for a topic."""
        with DatabaseConnection.cursor() as cursor:
            cursor.execute("""
                SELECT id, topic_id, name, description, evidence_count,
                       strength_score, opportunity_score, created_at
                FROM pain_clusters
                WHERE topic_id = ?
                ORDER BY opportunity_score DESC
                LIMIT ?
            """, (topic_id, limit))

            return [self._row_to_cluster(row) for row in cursor.fetchall()]

    def add_cluster(self, cluster: PainCluster) -> Optional[int]:
        """Add a new pain cluster. Returns the new ID."""
        try:
            with DatabaseConnection.transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO pain_clusters (topic_id, name, description,
                                              evidence_count, strength_score,
                                              opportunity_score)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    cluster.topic_id, cluster.name, cluster.description,
                    cluster.evidence_count, cluster.strength_score,
                    cluster.opportunity_score
                ))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error adding pain cluster: {e}")
            raise

    def _row_to_evidence(self, row) -> PainEvidence:
        """Convert a database row to PainEvidence."""
        # Parse JSON fields
        lenses = []
        if row["human_lenses"]:
            try:
                lenses = json.loads(row["human_lenses"])
            except json.JSONDecodeError:
                pass

        return PainEvidence(
            id=row["id"],
            post_id=row["post_id"],
            topic_id=row["topic_id"],
            verbatim_quote=row["verbatim_quote"],
            question_type=row["question_type"],
            human_lenses=lenses,
            industry=row["industry"] or "",
            emotion=row["emotion"] or "",
            source_url=row["source_url"] or "",
            quality_score=row["quality_score"] or 0.0,
            flagged_for_removal=bool(row["flagged_for_removal"]),
        )

    def _row_to_cluster(self, row) -> PainCluster:
        """Convert a database row to PainCluster."""
        return PainCluster(
            id=row["id"],
            topic_id=row["topic_id"],
            name=row["name"],
            description=row["description"] or "",
            evidence_count=row["evidence_count"] or 0,
            strength_score=row["strength_score"] or 0.0,
            opportunity_score=row["opportunity_score"] or 0.0,
        )
