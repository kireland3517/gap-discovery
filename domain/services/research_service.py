"""
Research service for orchestrating the research workflow.

Provides a high-level API for running research sessions using
the pipeline architecture.
"""

import asyncio
import logging
from typing import Callable, Optional

from pipeline import Pipeline, PipelineContext, EventBus, PipelineEvent
from pipeline.context import ResearchConfig as PipelineResearchConfig
from pipeline.stages import ScrapeStage, ValidationStage, SynthesisStage, ClusteringStage
from state import ResearchSession, ResearchSessionState
from infrastructure.repositories import SessionRepository

logger = logging.getLogger(__name__)


class ResearchService:
    """
    High-level service for running research sessions.

    Coordinates:
    - Pipeline execution
    - State machine transitions
    - Session persistence
    - Event notifications
    """

    def __init__(
        self,
        session_repository: Optional[SessionRepository] = None,
        on_progress: Optional[Callable[[dict], None]] = None
    ):
        """
        Initialize the research service.

        Args:
            session_repository: Repository for session persistence
            on_progress: Callback for progress updates
        """
        self.session_repository = session_repository or SessionRepository()
        self.on_progress = on_progress
        self._current_session: Optional[ResearchSession] = None
        self._current_pipeline: Optional[Pipeline] = None

    def create_session(
        self,
        topic: str,
        keywords: Optional[list[str]] = None,
        platforms: Optional[list[str]] = None
    ) -> ResearchSession:
        """
        Create a new research session.

        Args:
            topic: Research topic
            keywords: Optional list of keywords
            platforms: Optional list of platforms to scrape
        """
        session = ResearchSession(
            on_state_change=self._handle_state_change
        )
        session.configure(
            topic=topic,
            keywords=keywords or [],
            platforms=platforms or []
        )

        self._current_session = session

        # Persist initial state
        self._persist_session()

        logger.info(f"Created research session {session.session_id} for topic '{topic}'")
        return session

    def get_session(self, session_id: str) -> Optional[ResearchSession]:
        """Get a session by ID (from memory or persistence)."""
        if self._current_session and self._current_session.session_id == session_id:
            return self._current_session

        # Try to load from persistence
        data = self.session_repository.get_by_id(session_id)
        if data:
            session = self._restore_session(data)
            return session

        return None

    async def run_full_pipeline(
        self,
        session: Optional[ResearchSession] = None
    ) -> PipelineContext:
        """
        Run the complete research pipeline.

        Args:
            session: Session to run (uses current if not provided)

        Returns:
            PipelineContext with results
        """
        session = session or self._current_session
        if not session:
            raise ValueError("No session available")

        if session.state != ResearchSessionState.PLANNING:
            raise ValueError(f"Cannot start pipeline from {session.state.value} state")

        # Create event bus with progress forwarding
        event_bus = EventBus()
        event_bus.subscribe_all(self._handle_pipeline_event)

        # Create pipeline
        pipeline = Pipeline(
            name=f"research_{session.session_id}",
            event_bus=event_bus
        )

        # Add stages
        pipeline.add_stages(
            ScrapeStage(scrapers=session.data.platforms or None),
            ValidationStage(),
            SynthesisStage(),
            ClusteringStage()
        )

        self._current_pipeline = pipeline

        # Create context
        context = PipelineContext(
            config=PipelineResearchConfig(
                topic=session.data.topic,
                keywords=session.data.keywords,
                platforms=session.data.platforms
            ),
            session_id=session.session_id
        )

        # Start session
        session.start()
        self._persist_session()

        try:
            # Run pipeline
            context = await pipeline.run(context)

            # Update session with results
            if context.phase.value == "completed":
                session.complete_scraping(len(context.raw_posts))
                session.complete_processing(
                    evidence_extracted=len(context.validated_evidence),
                    themes_synthesized=len(context.synthesized_themes),
                    clusters_identified=len(context.clustered_patterns)
                )
            else:
                error_msg = "; ".join([e.get("error_message", "") for e in context.errors])
                session.fail(error_msg)

            self._persist_session()

        except Exception as e:
            logger.exception("Pipeline failed")
            session.fail(str(e))
            self._persist_session()
            raise

        finally:
            self._current_pipeline = None

        return context

    async def run_scrape_only(
        self,
        session: Optional[ResearchSession] = None
    ) -> int:
        """
        Run only the scraping stage.

        Returns:
            Number of posts collected
        """
        session = session or self._current_session
        if not session:
            raise ValueError("No session available")

        # Create event bus
        event_bus = EventBus()
        event_bus.subscribe_all(self._handle_pipeline_event)

        # Create context
        context = PipelineContext(
            config=PipelineResearchConfig(
                topic=session.data.topic,
                keywords=session.data.keywords,
                platforms=session.data.platforms
            ),
            session_id=session.session_id
        )

        # Run scrape stage
        stage = ScrapeStage(scrapers=session.data.platforms or None)
        result = await stage.run(context)

        if result.success:
            session.data.posts_collected = len(context.raw_posts)
            self._persist_session()

        return len(context.raw_posts)

    def cancel(self) -> bool:
        """Cancel the current running pipeline."""
        if self._current_pipeline:
            self._current_pipeline.cancel()

        if self._current_session:
            result = self._current_session.cancel()
            self._persist_session()
            return result

        return False

    def get_progress(self) -> dict:
        """Get current progress information."""
        progress = {
            "session": None,
            "pipeline": None
        }

        if self._current_session:
            progress["session"] = self._current_session.get_status()

        if self._current_pipeline:
            progress["pipeline"] = self._current_pipeline.get_progress()

        return progress

    def _handle_state_change(
        self,
        from_state: ResearchSessionState,
        to_state: ResearchSessionState,
        transition_name: str
    ):
        """Handle session state changes."""
        logger.info(f"Session state: {from_state.value} -> {to_state.value}")

        if self.on_progress:
            self.on_progress({
                "type": "state_change",
                "from_state": from_state.value,
                "to_state": to_state.value,
                "transition": transition_name
            })

    def _handle_pipeline_event(self, payload):
        """Handle pipeline events."""
        if self.on_progress:
            self.on_progress({
                "type": "pipeline_event",
                "event": payload.event.value,
                "stage": payload.stage_name,
                "data": payload.data,
                "metrics": payload.metrics
            })

    def _persist_session(self):
        """Persist current session state."""
        if not self._current_session:
            return

        session = self._current_session
        data = {
            "session_id": session.session_id,
            "state": session.state.value,
            "topic": session.data.topic,
            "keywords": session.data.keywords,
            "platforms": session.data.platforms,
            "posts_collected": session.data.posts_collected,
            "evidence_extracted": session.data.evidence_extracted,
            "themes_synthesized": session.data.themes_synthesized,
            "clusters_identified": session.data.clusters_identified,
            "errors": session.data.errors,
            "started_at": session.data.started_at.isoformat() if session.data.started_at else None,
            "completed_at": session.data.completed_at.isoformat() if session.data.completed_at else None,
        }

        self.session_repository.save(data)

    def _restore_session(self, data: dict) -> ResearchSession:
        """Restore a session from persisted data."""
        # Note: This is a simplified restoration that doesn't
        # restore the full state machine history
        session = ResearchSession(
            session_id=data["session_id"],
            on_state_change=self._handle_state_change
        )

        session.data.topic = data.get("topic", "")
        session.data.keywords = data.get("keywords", [])
        session.data.platforms = data.get("platforms", [])
        session.data.posts_collected = data.get("posts_collected", 0)
        session.data.evidence_extracted = data.get("evidence_extracted", 0)
        session.data.themes_synthesized = data.get("themes_synthesized", 0)
        session.data.clusters_identified = data.get("clusters_identified", 0)
        session.data.errors = data.get("errors", [])

        return session
