"""
Generic state machine implementation.

Provides a reusable state machine with:
- Typed states and transitions
- Guard conditions for transitions
- Event emission on state changes
- Transition history tracking
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar
import logging

logger = logging.getLogger(__name__)


# Type variable for state enum
S = TypeVar('S', bound=Enum)


@dataclass
class State(Generic[S]):
    """Represents a state in the state machine."""
    name: S
    on_enter: Optional[Callable[['StateMachine', Any], None]] = None
    on_exit: Optional[Callable[['StateMachine', Any], None]] = None

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, State):
            return self.name == other.name
        return self.name == other


@dataclass
class Transition(Generic[S]):
    """Represents a transition between states."""
    name: str
    from_state: S
    to_state: S
    guard: Optional[Callable[['StateMachine', Any], bool]] = None
    action: Optional[Callable[['StateMachine', Any], None]] = None

    def can_execute(self, machine: 'StateMachine', context: Any = None) -> bool:
        """Check if this transition can be executed."""
        if self.guard is None:
            return True
        return self.guard(machine, context)


@dataclass
class TransitionRecord:
    """Record of a completed transition."""
    transition_name: str
    from_state: str
    to_state: str
    timestamp: datetime = field(default_factory=datetime.now)
    context: Optional[dict] = None


class StateMachine(Generic[S]):
    """
    Generic state machine implementation.

    Example usage:
        class OrderState(Enum):
            PENDING = "pending"
            PROCESSING = "processing"
            SHIPPED = "shipped"

        machine = StateMachine(OrderState.PENDING)
        machine.add_transition("process", OrderState.PENDING, OrderState.PROCESSING)
        machine.add_transition("ship", OrderState.PROCESSING, OrderState.SHIPPED)

        machine.trigger("process")  # Moves to PROCESSING
        machine.trigger("ship")     # Moves to SHIPPED
    """

    def __init__(
        self,
        initial_state: S,
        on_state_change: Optional[Callable[[S, S, str], None]] = None
    ):
        """
        Initialize the state machine.

        Args:
            initial_state: The starting state
            on_state_change: Optional callback(from_state, to_state, transition_name)
        """
        self._current_state = initial_state
        self._states: dict[S, State[S]] = {}
        self._transitions: dict[str, Transition[S]] = {}
        self._history: list[TransitionRecord] = []
        self._on_state_change = on_state_change
        self._max_history = 100

    @property
    def current_state(self) -> S:
        """Get the current state."""
        return self._current_state

    @property
    def history(self) -> list[TransitionRecord]:
        """Get the transition history."""
        return list(self._history)

    def add_state(
        self,
        state: S,
        on_enter: Optional[Callable[['StateMachine', Any], None]] = None,
        on_exit: Optional[Callable[['StateMachine', Any], None]] = None
    ) -> 'StateMachine[S]':
        """Add a state with optional enter/exit callbacks."""
        self._states[state] = State(name=state, on_enter=on_enter, on_exit=on_exit)
        return self

    def add_transition(
        self,
        name: str,
        from_state: S,
        to_state: S,
        guard: Optional[Callable[['StateMachine', Any], bool]] = None,
        action: Optional[Callable[['StateMachine', Any], None]] = None
    ) -> 'StateMachine[S]':
        """
        Add a transition between states.

        Args:
            name: Unique name for this transition
            from_state: Source state
            to_state: Target state
            guard: Optional function that must return True for transition to proceed
            action: Optional function to execute during transition

        Returns:
            Self for chaining
        """
        self._transitions[name] = Transition(
            name=name,
            from_state=from_state,
            to_state=to_state,
            guard=guard,
            action=action
        )
        return self

    def can_trigger(self, transition_name: str, context: Any = None) -> bool:
        """Check if a transition can be triggered."""
        if transition_name not in self._transitions:
            return False

        transition = self._transitions[transition_name]

        # Check if we're in the right state
        if transition.from_state != self._current_state:
            return False

        # Check guard condition
        return transition.can_execute(self, context)

    def get_available_transitions(self) -> list[str]:
        """Get list of transitions available from current state."""
        return [
            name for name, trans in self._transitions.items()
            if trans.from_state == self._current_state
        ]

    def trigger(self, transition_name: str, context: Any = None) -> bool:
        """
        Trigger a transition by name.

        Args:
            transition_name: Name of the transition to trigger
            context: Optional context passed to guards and actions

        Returns:
            True if transition succeeded, False otherwise
        """
        if transition_name not in self._transitions:
            logger.warning(f"Unknown transition: {transition_name}")
            return False

        transition = self._transitions[transition_name]

        # Validate current state
        if transition.from_state != self._current_state:
            logger.warning(
                f"Cannot trigger {transition_name}: "
                f"expected state {transition.from_state.value}, "
                f"current state {self._current_state.value}"
            )
            return False

        # Check guard
        if not transition.can_execute(self, context):
            logger.info(f"Transition {transition_name} blocked by guard")
            return False

        from_state = self._current_state
        to_state = transition.to_state

        # Execute exit callback
        if from_state in self._states and self._states[from_state].on_exit:
            try:
                self._states[from_state].on_exit(self, context)
            except Exception as e:
                logger.error(f"Error in on_exit for {from_state}: {e}")

        # Execute transition action
        if transition.action:
            try:
                transition.action(self, context)
            except Exception as e:
                logger.error(f"Error in transition action for {transition_name}: {e}")

        # Change state
        self._current_state = to_state

        # Execute enter callback
        if to_state in self._states and self._states[to_state].on_enter:
            try:
                self._states[to_state].on_enter(self, context)
            except Exception as e:
                logger.error(f"Error in on_enter for {to_state}: {e}")

        # Record history
        record = TransitionRecord(
            transition_name=transition_name,
            from_state=from_state.value if hasattr(from_state, 'value') else str(from_state),
            to_state=to_state.value if hasattr(to_state, 'value') else str(to_state),
            context={"type": type(context).__name__} if context else None
        )
        self._history.append(record)

        # Trim history if needed
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Notify state change
        if self._on_state_change:
            try:
                self._on_state_change(from_state, to_state, transition_name)
            except Exception as e:
                logger.error(f"Error in state change callback: {e}")

        logger.info(f"State transition: {from_state.value} -> {to_state.value} ({transition_name})")
        return True

    def reset(self, initial_state: S) -> None:
        """Reset the state machine to a specific state."""
        self._current_state = initial_state
        self._history.clear()
        logger.info(f"State machine reset to {initial_state.value}")

    def get_state_info(self) -> dict:
        """Get current state information."""
        return {
            "current_state": self._current_state.value if hasattr(self._current_state, 'value') else str(self._current_state),
            "available_transitions": self.get_available_transitions(),
            "history_length": len(self._history),
            "last_transition": self._history[-1].transition_name if self._history else None
        }
