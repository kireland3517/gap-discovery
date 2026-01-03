"""
Pipeline orchestrator for chaining and executing stages.

The Pipeline class manages the execution of stages in sequence,
handling events, errors, and rollback.
"""

import logging
import uuid
from typing import Optional
from datetime import datetime

from .base import PipelineStage, StageResult, StageStatus
from .events import EventBus, PipelineEvent, EventPayload
from .context import PipelineContext, ResearchPhase

logger = logging.getLogger(__name__)


class Pipeline:
    """
    Orchestrates the execution of pipeline stages.

    Features:
    - Sequential stage execution
    - Event emission at each step
    - Error handling with optional continue-on-failure
    - Metrics collection
    """

    def __init__(
        self,
        name: str = "research_pipeline",
        event_bus: Optional[EventBus] = None,
        stop_on_failure: bool = True
    ):
        self.name = name
        self.event_bus = event_bus or EventBus()
        self.stop_on_failure = stop_on_failure
        self._stages: list[PipelineStage] = []
        self._is_running = False
        self._is_cancelled = False

    def add_stage(self, stage: PipelineStage) -> 'Pipeline':
        """Add a stage to the pipeline. Returns self for chaining."""
        self._stages.append(stage)
        return self

    def add_stages(self, *stages: PipelineStage) -> 'Pipeline':
        """Add multiple stages to the pipeline."""
        for stage in stages:
            self._stages.append(stage)
        return self

    @property
    def stages(self) -> list[PipelineStage]:
        """Get the list of stages."""
        return list(self._stages)

    @property
    def is_running(self) -> bool:
        """Check if the pipeline is currently running."""
        return self._is_running

    def cancel(self) -> None:
        """Request cancellation of the running pipeline."""
        self._is_cancelled = True
        logger.info(f"Pipeline {self.name} cancellation requested")

    def _emit(
        self,
        event: PipelineEvent,
        stage_name: Optional[str] = None,
        data: any = None,
        error: Optional[Exception] = None,
        metrics: Optional[dict] = None
    ) -> None:
        """Emit an event through the event bus."""
        self.event_bus.emit(EventPayload(
            event=event,
            stage_name=stage_name,
            data=data,
            error=error,
            metrics=metrics or {}
        ))

    async def run(self, context: PipelineContext) -> PipelineContext:
        """
        Execute all stages in sequence.

        Args:
            context: The pipeline context with initial configuration

        Returns:
            Updated context with results from all stages
        """
        if self._is_running:
            raise RuntimeError("Pipeline is already running")

        self._is_running = True
        self._is_cancelled = False

        # Generate session ID if not set
        if not context.session_id:
            context.session_id = str(uuid.uuid4())[:8]

        # Emit pipeline started
        self._emit(
            PipelineEvent.PIPELINE_STARTED,
            data={"stages": [s.name for s in self._stages]},
            metrics={"stage_count": len(self._stages)}
        )

        logger.info(f"Pipeline {self.name} started with {len(self._stages)} stages")

        completed_stages = 0
        failed_stages = 0

        try:
            for i, stage in enumerate(self._stages):
                # Check for cancellation
                if self._is_cancelled:
                    self._emit(PipelineEvent.PIPELINE_CANCELLED)
                    context.add_error("pipeline", Exception("Pipeline cancelled by user"))
                    break

                # Emit stage started
                self._emit(
                    PipelineEvent.STAGE_STARTED,
                    stage_name=stage.name,
                    metrics={"stage_index": i, "total_stages": len(self._stages)}
                )

                logger.info(f"Starting stage {i + 1}/{len(self._stages)}: {stage.name}")

                # Run the stage
                start_time = datetime.now()
                result = await stage.run(context)
                duration = (datetime.now() - start_time).total_seconds()

                # Update context metrics
                context.update_metric(f"{stage.name}_duration_seconds", duration)

                if result.success:
                    completed_stages += 1
                    self._emit(
                        PipelineEvent.STAGE_COMPLETED,
                        stage_name=stage.name,
                        data=result.data,
                        metrics={**result.metrics, "duration_seconds": duration}
                    )
                    logger.info(f"Stage {stage.name} completed in {duration:.1f}s")

                else:
                    failed_stages += 1
                    context.add_error(stage.name, result.error or Exception("Unknown error"))
                    self._emit(
                        PipelineEvent.STAGE_FAILED,
                        stage_name=stage.name,
                        error=result.error,
                        metrics={"duration_seconds": duration}
                    )
                    logger.error(f"Stage {stage.name} failed: {result.error}")

                    if self.stop_on_failure:
                        break

            # Determine final status
            if self._is_cancelled:
                context.mark_failed()
            elif failed_stages > 0 and self.stop_on_failure:
                context.mark_failed()
                self._emit(
                    PipelineEvent.PIPELINE_FAILED,
                    metrics={
                        "completed_stages": completed_stages,
                        "failed_stages": failed_stages,
                        "duration_seconds": context.get_duration_seconds()
                    }
                )
            else:
                context.mark_completed()
                self._emit(
                    PipelineEvent.PIPELINE_COMPLETED,
                    metrics={
                        "completed_stages": completed_stages,
                        "failed_stages": failed_stages,
                        "duration_seconds": context.get_duration_seconds()
                    }
                )

            logger.info(
                f"Pipeline {self.name} finished: "
                f"{completed_stages} completed, {failed_stages} failed, "
                f"{context.get_duration_seconds():.1f}s total"
            )

        except Exception as e:
            logger.exception(f"Unexpected error in pipeline {self.name}")
            context.add_error("pipeline", e)
            context.mark_failed()
            self._emit(PipelineEvent.PIPELINE_FAILED, error=e)

        finally:
            self._is_running = False

        return context

    def get_progress(self) -> dict:
        """Get current progress information."""
        total = len(self._stages)
        completed = sum(1 for s in self._stages if s.status == StageStatus.COMPLETED)
        failed = sum(1 for s in self._stages if s.status == StageStatus.FAILED)
        running = sum(1 for s in self._stages if s.status == StageStatus.RUNNING)

        return {
            "total_stages": total,
            "completed_stages": completed,
            "failed_stages": failed,
            "running_stages": running,
            "pending_stages": total - completed - failed - running,
            "progress_percent": (completed / total * 100) if total > 0 else 0,
            "is_running": self._is_running,
            "is_cancelled": self._is_cancelled,
        }

    def __repr__(self) -> str:
        return f"Pipeline(name={self.name!r}, stages={len(self._stages)})"
