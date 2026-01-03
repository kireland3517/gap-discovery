"""
Event system for pipeline progress tracking.

Provides an EventBus for publishing and subscribing to pipeline events.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional
import logging

logger = logging.getLogger(__name__)


class PipelineEvent(Enum):
    """Events emitted during pipeline execution."""
    # Pipeline lifecycle
    PIPELINE_STARTED = "pipeline_started"
    PIPELINE_COMPLETED = "pipeline_completed"
    PIPELINE_FAILED = "pipeline_failed"
    PIPELINE_CANCELLED = "pipeline_cancelled"

    # Stage lifecycle
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    STAGE_SKIPPED = "stage_skipped"

    # Progress events
    STAGE_PROGRESS = "stage_progress"
    ITEMS_PROCESSED = "items_processed"

    # Data events
    DATA_COLLECTED = "data_collected"
    DATA_VALIDATED = "data_validated"
    DATA_SYNTHESIZED = "data_synthesized"


@dataclass
class EventPayload:
    """Payload for a pipeline event."""
    event: PipelineEvent
    timestamp: datetime = field(default_factory=datetime.now)
    stage_name: Optional[str] = None
    data: Any = None
    error: Optional[Exception] = None
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "event": self.event.value,
            "timestamp": self.timestamp.isoformat(),
            "stage_name": self.stage_name,
            "data": str(self.data) if self.data is not None else None,
            "error": str(self.error) if self.error else None,
            "metrics": self.metrics,
        }


# Type alias for event handlers
EventHandler = Callable[[EventPayload], None]


class EventBus:
    """
    Simple event bus for pipeline event pub/sub.

    Supports:
    - Subscribing to specific events or all events
    - Multiple handlers per event
    - Synchronous event dispatch
    """

    def __init__(self):
        self._handlers: dict[PipelineEvent, list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []
        self._event_history: list[EventPayload] = []
        self._max_history = 1000

    def subscribe(self, event: PipelineEvent, handler: EventHandler) -> None:
        """Subscribe a handler to a specific event."""
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe a handler to all events."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event: PipelineEvent, handler: EventHandler) -> None:
        """Unsubscribe a handler from a specific event."""
        if event in self._handlers and handler in self._handlers[event]:
            self._handlers[event].remove(handler)

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Unsubscribe a handler from all events."""
        if handler in self._global_handlers:
            self._global_handlers.remove(handler)

    def emit(self, payload: EventPayload) -> None:
        """
        Emit an event to all subscribed handlers.

        Events are dispatched synchronously.
        """
        # Store in history
        self._event_history.append(payload)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]

        # Dispatch to specific handlers
        handlers = self._handlers.get(payload.event, [])
        for handler in handlers:
            try:
                handler(payload)
            except Exception as e:
                logger.error(f"Error in event handler for {payload.event}: {e}")

        # Dispatch to global handlers
        for handler in self._global_handlers:
            try:
                handler(payload)
            except Exception as e:
                logger.error(f"Error in global event handler: {e}")

    def emit_simple(
        self,
        event: PipelineEvent,
        stage_name: Optional[str] = None,
        data: Any = None,
        error: Optional[Exception] = None,
        metrics: Optional[dict] = None
    ) -> None:
        """Convenience method to emit an event with common fields."""
        self.emit(EventPayload(
            event=event,
            stage_name=stage_name,
            data=data,
            error=error,
            metrics=metrics or {}
        ))

    def get_history(self, event: Optional[PipelineEvent] = None) -> list[EventPayload]:
        """Get event history, optionally filtered by event type."""
        if event is None:
            return list(self._event_history)
        return [e for e in self._event_history if e.event == event]

    def clear_history(self) -> None:
        """Clear event history."""
        self._event_history.clear()

    def clear_handlers(self) -> None:
        """Clear all handlers."""
        self._handlers.clear()
        self._global_handlers.clear()
