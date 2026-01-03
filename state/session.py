"""
Research session state machine.

Defines the states and transitions for a research session workflow.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
import logging
import uuid

from .machine import StateMachine

logger = logging.getLogger(__name__)


class ResearchSessionState(Enum):
    """States for a research session."""
    PLANNING = "planning"           # Configuring research parameters
    SCRAPING = "scraping"          # Collecting data from sources
    PROCESSING = "processing"      # Running validation and synthesis
    REVIEWING = "reviewing"        # Human review of results
    COMPLETED = "completed"        # Final state - success
    FAILED = "failed"              # Final state - failure
    CANCELLED = "cancelled"        # Final state - user cancelled


@dataclass
class ResearchSessionData:
    """Data associated with a research session."""
    session_id: str = ""
    topic: str = ""
    keywords: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)

    # Progress tracking
    posts_collected: int = 0
    evidence_extracted: int = 0
    themes_synthesized: int = 0
    clusters_identified: int = 0

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Errors
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "topic": self.topic,
            "keywords": self.keywords,
            "platforms": self.platforms,
            "posts_collected": self.posts_collected,
            "evidence_extracted": self.evidence_extracted,
            "themes_synthesized": self.themes_synthesized,
            "clusters_identified": self.clusters_identified,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "errors": self.errors
        }


class ResearchSession:
    """
    Research session with state machine for workflow management.

    States:
        PLANNING -> SCRAPING -> PROCESSING -> REVIEWING -> COMPLETED
                                           \-> FAILED
        Any state -> CANCELLED (via cancel)

    Transitions:
        start_research: PLANNING -> SCRAPING
        scraping_complete: SCRAPING -> PROCESSING
        processing_complete: PROCESSING -> REVIEWING
        approve: REVIEWING -> COMPLETED
        request_more_data: REVIEWING -> SCRAPING
        fail: PROCESSING/SCRAPING -> FAILED
        cancel: Any -> CANCELLED
        reset: Any -> PLANNING
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        on_state_change: Optional[Callable[[ResearchSessionState, ResearchSessionState, str], None]] = None
    ):
        """
        Initialize a research session.

        Args:
            session_id: Optional session identifier. Generated if not provided.
            on_state_change: Optional callback for state changes.
        """
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.data = ResearchSessionData(session_id=self.session_id)
        self._on_state_change = on_state_change

        # Create state machine
        self._machine = StateMachine[ResearchSessionState](
            initial_state=ResearchSessionState.PLANNING,
            on_state_change=self._handle_state_change
        )

        # Configure states
        self._configure_states()

        # Configure transitions
        self._configure_transitions()

    def _configure_states(self):
        """Configure state enter/exit callbacks."""
        self._machine.add_state(
            ResearchSessionState.PLANNING,
            on_enter=self._on_enter_planning
        )
        self._machine.add_state(
            ResearchSessionState.SCRAPING,
            on_enter=self._on_enter_scraping
        )
        self._machine.add_state(
            ResearchSessionState.PROCESSING,
            on_enter=self._on_enter_processing
        )
        self._machine.add_state(
            ResearchSessionState.REVIEWING,
            on_enter=self._on_enter_reviewing
        )
        self._machine.add_state(
            ResearchSessionState.COMPLETED,
            on_enter=self._on_enter_completed
        )
        self._machine.add_state(
            ResearchSessionState.FAILED,
            on_enter=self._on_enter_failed
        )

    def _configure_transitions(self):
        """Configure state transitions."""
        # Normal flow
        self._machine.add_transition(
            "start_research",
            ResearchSessionState.PLANNING,
            ResearchSessionState.SCRAPING,
            guard=self._guard_has_topic
        )
        self._machine.add_transition(
            "scraping_complete",
            ResearchSessionState.SCRAPING,
            ResearchSessionState.PROCESSING
        )
        self._machine.add_transition(
            "processing_complete",
            ResearchSessionState.PROCESSING,
            ResearchSessionState.REVIEWING
        )
        self._machine.add_transition(
            "approve",
            ResearchSessionState.REVIEWING,
            ResearchSessionState.COMPLETED
        )

        # Review loop
        self._machine.add_transition(
            "request_more_data",
            ResearchSessionState.REVIEWING,
            ResearchSessionState.SCRAPING
        )

        # Failure transitions
        self._machine.add_transition(
            "fail",
            ResearchSessionState.SCRAPING,
            ResearchSessionState.FAILED
        )
        self._machine.add_transition(
            "fail",
            ResearchSessionState.PROCESSING,
            ResearchSessionState.FAILED
        )

        # Reset transition (from any non-terminal state)
        for state in [ResearchSessionState.PLANNING, ResearchSessionState.SCRAPING,
                     ResearchSessionState.PROCESSING, ResearchSessionState.REVIEWING]:
            self._machine.add_transition(
                f"reset_from_{state.value}",
                state,
                ResearchSessionState.PLANNING
            )

        # Cancel transition (from any non-terminal state)
        for state in [ResearchSessionState.PLANNING, ResearchSessionState.SCRAPING,
                     ResearchSessionState.PROCESSING, ResearchSessionState.REVIEWING]:
            self._machine.add_transition(
                f"cancel_from_{state.value}",
                state,
                ResearchSessionState.CANCELLED
            )

    # Guard conditions
    def _guard_has_topic(self, machine: StateMachine, context: Any) -> bool:
        """Guard: require topic to be set before starting."""
        return bool(self.data.topic)

    # State enter callbacks
    def _on_enter_planning(self, machine: StateMachine, context: Any):
        logger.info(f"Session {self.session_id}: Entering PLANNING state")

    def _on_enter_scraping(self, machine: StateMachine, context: Any):
        logger.info(f"Session {self.session_id}: Entering SCRAPING state")
        if not self.data.started_at:
            self.data.started_at = datetime.now()

    def _on_enter_processing(self, machine: StateMachine, context: Any):
        logger.info(f"Session {self.session_id}: Entering PROCESSING state")

    def _on_enter_reviewing(self, machine: StateMachine, context: Any):
        logger.info(f"Session {self.session_id}: Entering REVIEWING state")

    def _on_enter_completed(self, machine: StateMachine, context: Any):
        logger.info(f"Session {self.session_id}: Entering COMPLETED state")
        self.data.completed_at = datetime.now()

    def _on_enter_failed(self, machine: StateMachine, context: Any):
        logger.info(f"Session {self.session_id}: Entering FAILED state")
        self.data.completed_at = datetime.now()

    def _handle_state_change(
        self,
        from_state: ResearchSessionState,
        to_state: ResearchSessionState,
        transition_name: str
    ):
        """Handle state change and forward to external callback."""
        if self._on_state_change:
            self._on_state_change(from_state, to_state, transition_name)

    # Public API
    @property
    def state(self) -> ResearchSessionState:
        """Get current state."""
        return self._machine.current_state

    @property
    def is_terminal(self) -> bool:
        """Check if session is in a terminal state."""
        return self.state in [
            ResearchSessionState.COMPLETED,
            ResearchSessionState.FAILED,
            ResearchSessionState.CANCELLED
        ]

    @property
    def is_active(self) -> bool:
        """Check if session is actively processing."""
        return self.state in [
            ResearchSessionState.SCRAPING,
            ResearchSessionState.PROCESSING
        ]

    def configure(self, topic: str, keywords: list[str] = None, platforms: list[str] = None):
        """Configure the research session parameters."""
        if self.state != ResearchSessionState.PLANNING:
            raise ValueError(f"Cannot configure session in {self.state.value} state")

        self.data.topic = topic
        self.data.keywords = keywords or []
        self.data.platforms = platforms or []
        logger.info(f"Session {self.session_id}: Configured for topic '{topic}'")

    def start(self) -> bool:
        """Start the research session."""
        return self._machine.trigger("start_research")

    def complete_scraping(self, posts_collected: int = 0) -> bool:
        """Mark scraping as complete."""
        self.data.posts_collected = posts_collected
        return self._machine.trigger("scraping_complete")

    def complete_processing(
        self,
        evidence_extracted: int = 0,
        themes_synthesized: int = 0,
        clusters_identified: int = 0
    ) -> bool:
        """Mark processing as complete."""
        self.data.evidence_extracted = evidence_extracted
        self.data.themes_synthesized = themes_synthesized
        self.data.clusters_identified = clusters_identified
        return self._machine.trigger("processing_complete")

    def approve(self) -> bool:
        """Approve the results and complete the session."""
        return self._machine.trigger("approve")

    def request_more_data(self) -> bool:
        """Request more data and go back to scraping."""
        return self._machine.trigger("request_more_data")

    def fail(self, error: str = None) -> bool:
        """Mark the session as failed."""
        if error:
            self.data.errors.append(error)
        return self._machine.trigger("fail")

    def cancel(self) -> bool:
        """Cancel the session."""
        transition = f"cancel_from_{self.state.value}"
        return self._machine.trigger(transition)

    def reset(self) -> bool:
        """Reset the session to planning state."""
        transition = f"reset_from_{self.state.value}"
        result = self._machine.trigger(transition)
        if result:
            # Clear data but keep session_id
            session_id = self.session_id
            self.data = ResearchSessionData(session_id=session_id)
        return result

    def get_available_actions(self) -> list[str]:
        """Get list of available actions from current state."""
        actions = []
        transitions = self._machine.get_available_transitions()

        # Map transition names to user-friendly actions
        action_map = {
            "start_research": "start",
            "scraping_complete": "complete_scraping",
            "processing_complete": "complete_processing",
            "approve": "approve",
            "request_more_data": "request_more_data",
            "fail": "fail"
        }

        for trans in transitions:
            if trans in action_map:
                actions.append(action_map[trans])
            elif trans.startswith("reset_"):
                actions.append("reset")
            elif trans.startswith("cancel_"):
                actions.append("cancel")

        return list(set(actions))  # Remove duplicates

    def get_status(self) -> dict:
        """Get full status of the session."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "is_terminal": self.is_terminal,
            "is_active": self.is_active,
            "available_actions": self.get_available_actions(),
            "data": self.data.to_dict(),
            "history": [
                {
                    "transition": r.transition_name,
                    "from": r.from_state,
                    "to": r.to_state,
                    "timestamp": r.timestamp.isoformat()
                }
                for r in self._machine.history
            ]
        }
