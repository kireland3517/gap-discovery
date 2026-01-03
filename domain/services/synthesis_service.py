"""
Synthesis service for AI-powered analysis.

Wraps the synthesis operations with proper error handling
and cost tracking.
"""

import logging
from typing import Optional

from domain.models import PainEvidence, PainCluster, Theme
from infrastructure.repositories import PainRepository

logger = logging.getLogger(__name__)


class SynthesisService:
    """
    Service for AI synthesis operations.

    Provides:
    - Pain evidence extraction
    - Theme synthesis
    - Cluster identification
    - Cost tracking
    """

    def __init__(self, pain_repository: Optional[PainRepository] = None):
        """
        Initialize the synthesis service.

        Args:
            pain_repository: Repository for storing results
        """
        self.pain_repository = pain_repository or PainRepository()

    def extract_evidence(
        self,
        posts: list[dict],
        topic_id: int
    ) -> list[PainEvidence]:
        """
        Extract pain evidence from posts.

        Args:
            posts: List of post dictionaries
            topic_id: Topic ID for storing results

        Returns:
            List of extracted PainEvidence objects
        """
        # Import synthesis functions
        from synthesize import extract_pain_evidence, get_circuit_breaker
        from scrape import load_config

        config = load_config()
        cb = get_circuit_breaker()

        # Check circuit breaker
        if cb.is_open():
            logger.warning("Circuit breaker is open, cannot extract evidence")
            return []

        # Extract evidence
        result = extract_pain_evidence(posts, config)
        if not result:
            return []

        evidence_list = []
        for item in result.get("pain_evidence", []):
            evidence = PainEvidence.from_dict(item)
            evidence.topic_id = topic_id

            # Store in database
            try:
                evidence_id = self.pain_repository.add_evidence(evidence)
                evidence.id = evidence_id
            except Exception as e:
                logger.error(f"Failed to store evidence: {e}")

            evidence_list.append(evidence)

        logger.info(f"Extracted {len(evidence_list)} pain evidence entries")
        return evidence_list

    def cluster_evidence(
        self,
        evidence_list: list[PainEvidence],
        topic_id: int
    ) -> list[PainCluster]:
        """
        Cluster related pain evidence.

        Args:
            evidence_list: List of pain evidence to cluster
            topic_id: Topic ID for storing results

        Returns:
            List of identified PainCluster objects
        """
        # Import synthesis functions
        from synthesize import validate_and_cluster, get_circuit_breaker
        from scrape import load_config

        config = load_config()
        cb = get_circuit_breaker()

        # Check circuit breaker
        if cb.is_open():
            logger.warning("Circuit breaker is open, cannot cluster evidence")
            return []

        # Convert to dict format for existing function
        evidence_dicts = [e.to_dict() for e in evidence_list]

        # Cluster
        result = validate_and_cluster(evidence_dicts, config)
        if not result:
            return []

        clusters = []
        for item in result.get("pain_clusters", []):
            cluster = PainCluster.from_dict(item)
            cluster.topic_id = topic_id

            # Store in database
            try:
                cluster_id = self.pain_repository.add_cluster(cluster)
                cluster.id = cluster_id
            except Exception as e:
                logger.error(f"Failed to store cluster: {e}")

            clusters.append(cluster)

        logger.info(f"Identified {len(clusters)} pain clusters")
        return clusters

    def synthesize_themes(
        self,
        evidence_list: list[PainEvidence]
    ) -> list[Theme]:
        """
        Synthesize themes from pain evidence.

        Args:
            evidence_list: List of pain evidence to analyze

        Returns:
            List of synthesized Theme objects
        """
        # Import synthesis functions
        from synthesize import batch_synthesize, get_circuit_breaker
        from scrape import load_config

        config = load_config()
        cb = get_circuit_breaker()

        # Check circuit breaker
        if cb.is_open():
            logger.warning("Circuit breaker is open, cannot synthesize themes")
            return []

        # Convert evidence to post-like format
        posts = []
        for e in evidence_list:
            posts.append({
                "id": e.post_id,
                "content": e.verbatim_quote,
                "question_type": e.question_type,
                "industry": e.industry,
                "emotion": e.emotion,
            })

        # Synthesize
        result = batch_synthesize(posts, config)
        if not result:
            return []

        themes = []
        for item in result.get("themes", []):
            theme = Theme.from_dict(item)
            themes.append(theme)

        logger.info(f"Synthesized {len(themes)} themes")
        return themes

    def get_circuit_breaker_status(self) -> dict:
        """Get the current circuit breaker status."""
        from synthesize import get_circuit_breaker
        return get_circuit_breaker().get_status()

    def reset_circuit_breaker(self) -> None:
        """Reset the circuit breaker."""
        from synthesize import reset_circuit_breaker
        reset_circuit_breaker()
        logger.info("Circuit breaker reset")
