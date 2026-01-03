"""
State management module for research sessions.

Provides a state machine for tracking research workflow state
and handling state transitions with event emission.
"""

from .machine import StateMachine, State, Transition
from .session import ResearchSessionState, ResearchSession

__all__ = [
    'StateMachine',
    'State',
    'Transition',
    'ResearchSessionState',
    'ResearchSession',
]
