"""
Synthesis stage for the research pipeline.

Synthesizes themes and patterns from validated pain evidence.
"""

import logging
from typing import Optional

from ..base import PipelineStage, StageResult, StageStatus
from ..context import PipelineContext, ResearchPhase

logger = logging.getLogger(__name__)


class SynthesisStage(PipelineStage):
    """
    Pipeline stage that synthesizes themes from pain evidence.

    Wraps the existing batch_synthesize() function from synthesize.py.
    Uses the CircuitBreaker for API cost protection.
    """

    def __init__(self, batch_size: int = 30):
        """
        Initialize the synthesis stage.

        Args:
            batch_size: Number of evidence entries to process per API call.
        """
        super().__init__(name="Synthesis")
        self.batch_size = batch_size

    def validate_input(self, context: PipelineContext) -> bool:
        """Validate that we have evidence to synthesize."""
        if not context.validated_evidence:
            logger.warning("No validated evidence to synthesize")
            # Return True to allow skipping - empty input is valid
            return True
        return True

    def validate_output(self, context: PipelineContext, result: StageResult) -> bool:
        """Validate that we generated some themes."""
        # Allow empty results - synthesis may not find patterns
        return True

    async def execute(self, context: PipelineContext) -> StageResult:
        """
        Execute the synthesis stage.

        Calls batch_synthesize() and stores themes in context.
        """
        context.phase = ResearchPhase.SYNTHESIZING

        if not context.validated_evidence:
            logger.info("No evidence to synthesize, skipping stage")
            return StageResult(
                status=StageStatus.COMPLETED,
                data={"themes_count": 0, "skipped": True},
                metrics={"themes_count": 0}
            )

        try:
            # Import here to avoid circular imports
            from synthesize import batch_synthesize, get_circuit_breaker
            from scrape import load_config

            config = load_config()
            cb = get_circuit_breaker()

            # Check circuit breaker before starting
            if cb.is_open():
                logger.warning("Circuit breaker open, skipping synthesis")
                return StageResult(
                    status=StageStatus.COMPLETED,
                    data={"themes_count": 0, "circuit_breaker_open": True},
                    metrics={"themes_count": 0}
                )

            # Convert evidence to post-like format for batch_synthesize
            # The function expects posts with content field
            posts_for_synthesis = []
            for evidence in context.validated_evidence:
                posts_for_synthesis.append({
                    "id": evidence.get("post_id", 0),
                    "content": evidence.get("verbatim_quote", ""),
                    "source": evidence.get("source", "unknown"),
                    "question_type": evidence.get("question_type", ""),
                    "emotion": evidence.get("emotion", ""),
                    "industry": evidence.get("industry", "")
                })

            logger.info(f"Synthesizing {len(posts_for_synthesis)} evidence entries")

            # Call batch_synthesize
            result = batch_synthesize(posts_for_synthesis, config)

            themes = []
            if result:
                themes = result.get("themes", [])

                # Store raw synthesis result
                context.synthesized_themes = themes

                logger.info(f"Synthesized {len(themes)} themes")
            else:
                logger.warning("Synthesis returned no results")

            # Update metrics
            context.update_metric("themes_synthesized", len(themes))
            context.update_metric("circuit_breaker_status", cb.get_status())

            return StageResult(
                status=StageStatus.COMPLETED,
                data={"themes_count": len(themes)},
                metrics={"themes_count": len(themes)}
            )

        except Exception as e:
            logger.exception("Synthesis failed")
            return StageResult(
                status=StageStatus.FAILED,
                error=e
            )
