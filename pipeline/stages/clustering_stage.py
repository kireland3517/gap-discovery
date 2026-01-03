"""
Clustering stage for the research pipeline.

Validates evidence and identifies pain clusters from synthesized themes.
"""

import logging
from typing import Optional

from ..base import PipelineStage, StageResult, StageStatus
from ..context import PipelineContext, ResearchPhase

logger = logging.getLogger(__name__)


class ClusteringStage(PipelineStage):
    """
    Pipeline stage that clusters pain patterns from evidence.

    Wraps the existing validate_and_cluster() function from synthesize.py.
    Only creates clusters when 3+ evidence entries share the same pain.
    Uses the CircuitBreaker for API cost protection.
    """

    def __init__(self, min_cluster_size: int = 3):
        """
        Initialize the clustering stage.

        Args:
            min_cluster_size: Minimum evidence entries needed to form a cluster.
        """
        super().__init__(name="Clustering")
        self.min_cluster_size = min_cluster_size

    def validate_input(self, context: PipelineContext) -> bool:
        """Validate that we have evidence to cluster."""
        if not context.validated_evidence:
            logger.warning("No validated evidence to cluster")
            # Return True to allow skipping - empty input is valid
            return True
        return True

    def validate_output(self, context: PipelineContext, result: StageResult) -> bool:
        """Validate clustering output."""
        # Allow empty results - not all evidence forms clusters
        return True

    async def execute(self, context: PipelineContext) -> StageResult:
        """
        Execute the clustering stage.

        Calls validate_and_cluster() and stores patterns in context.
        """
        context.phase = ResearchPhase.CLUSTERING

        if not context.validated_evidence:
            logger.info("No evidence to cluster, skipping stage")
            return StageResult(
                status=StageStatus.COMPLETED,
                data={"clusters_count": 0, "skipped": True},
                metrics={"clusters_count": 0}
            )

        try:
            # Import here to avoid circular imports
            from synthesize import validate_and_cluster, get_circuit_breaker
            from scrape import load_config

            config = load_config()
            cb = get_circuit_breaker()

            # Check circuit breaker before starting
            if cb.is_open():
                logger.warning("Circuit breaker open, using default clustering")
                # Return with minimal processing
                context.clustered_patterns = []
                return StageResult(
                    status=StageStatus.COMPLETED,
                    data={"clusters_count": 0, "circuit_breaker_open": True},
                    metrics={"clusters_count": 0}
                )

            logger.info(f"Clustering {len(context.validated_evidence)} evidence entries")

            # Call validate_and_cluster
            result = validate_and_cluster(context.validated_evidence, config)

            clusters = []
            failed_solutions = []

            if result:
                clusters = result.get("pain_clusters", [])
                failed_solutions = result.get("aggregated_failed_solutions", [])

                # Filter clusters by minimum size
                clusters = [c for c in clusters if c.get("evidence_count", 0) >= self.min_cluster_size]

                # Store in context
                context.clustered_patterns = clusters

                logger.info(
                    f"Identified {len(clusters)} clusters, "
                    f"{len(failed_solutions)} failed solutions"
                )
            else:
                logger.warning("Clustering returned no results")
                context.clustered_patterns = []

            # Update metrics
            context.update_metric("clusters_identified", len(clusters))
            context.update_metric("failed_solutions", len(failed_solutions))
            context.update_metric("circuit_breaker_status", cb.get_status())

            return StageResult(
                status=StageStatus.COMPLETED,
                data={
                    "clusters_count": len(clusters),
                    "failed_solutions_count": len(failed_solutions)
                },
                metrics={
                    "clusters_count": len(clusters),
                    "failed_solutions_count": len(failed_solutions)
                }
            )

        except Exception as e:
            logger.exception("Clustering failed")
            return StageResult(
                status=StageStatus.FAILED,
                error=e
            )
