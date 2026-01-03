"""
Validation stage for the research pipeline.

Extracts pain evidence from posts using the four-question framework.
"""

import logging
from typing import Optional

from ..base import PipelineStage, StageResult, StageStatus
from ..context import PipelineContext, ResearchPhase

logger = logging.getLogger(__name__)


class ValidationStage(PipelineStage):
    """
    Pipeline stage that validates posts and extracts pain evidence.

    Wraps the existing extract_pain_evidence() function from synthesize.py.
    Uses the CircuitBreaker for API cost protection.
    """

    def __init__(self, batch_size: int = 20):
        """
        Initialize the validation stage.

        Args:
            batch_size: Number of posts to process per API call.
        """
        super().__init__(name="Validation")
        self.batch_size = batch_size

    def validate_input(self, context: PipelineContext) -> bool:
        """Validate that we have posts to process."""
        if not context.raw_posts:
            logger.warning("No posts to validate")
            # Return True to allow skipping - empty input is valid
            return True
        return True

    def validate_output(self, context: PipelineContext, result: StageResult) -> bool:
        """Validate that we extracted some evidence."""
        # Allow empty results - not all posts have pain evidence
        return True

    async def execute(self, context: PipelineContext) -> StageResult:
        """
        Execute the validation stage.

        Calls extract_pain_evidence() in batches and stores results in context.
        """
        context.phase = ResearchPhase.VALIDATING

        if not context.raw_posts:
            logger.info("No posts to validate, skipping stage")
            return StageResult(
                status=StageStatus.COMPLETED,
                data={"evidence_count": 0, "skipped": True},
                metrics={"evidence_count": 0}
            )

        try:
            # Import here to avoid circular imports
            from synthesize import extract_pain_evidence, get_circuit_breaker
            from scrape import load_config

            config = load_config()
            cb = get_circuit_breaker()

            all_evidence = []
            processed_count = 0
            batch_count = 0

            # Process in batches
            for i in range(0, len(context.raw_posts), self.batch_size):
                batch = context.raw_posts[i:i + self.batch_size]
                batch_count += 1

                logger.info(f"Processing batch {batch_count} ({len(batch)} posts)")

                # Check circuit breaker
                if cb.is_open():
                    logger.warning("Circuit breaker open, stopping validation")
                    context.add_error(
                        self.name,
                        Exception("Circuit breaker open"),
                        {"batch": batch_count, "processed": processed_count}
                    )
                    break

                # Extract pain evidence
                result = extract_pain_evidence(batch, config)

                if result:
                    evidence = result.get("pain_evidence", [])
                    all_evidence.extend(evidence)
                    processed_count += len(batch)

                    logger.info(f"  Extracted {len(evidence)} evidence entries")
                else:
                    logger.warning(f"  Batch {batch_count} returned no results")

            # Store in context
            context.validated_evidence = all_evidence

            # Update metrics
            context.update_metric("evidence_extracted", len(all_evidence))
            context.update_metric("posts_processed", processed_count)
            context.update_metric("circuit_breaker_status", cb.get_status())

            logger.info(
                f"Validation complete: {len(all_evidence)} evidence entries "
                f"from {processed_count} posts"
            )

            return StageResult(
                status=StageStatus.COMPLETED,
                data={
                    "evidence_count": len(all_evidence),
                    "posts_processed": processed_count
                },
                metrics={
                    "evidence_count": len(all_evidence),
                    "posts_processed": processed_count,
                    "batches_processed": batch_count
                }
            )

        except Exception as e:
            logger.exception("Validation failed")
            return StageResult(
                status=StageStatus.FAILED,
                error=e
            )
