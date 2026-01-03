"""
Pipeline module for event-driven research processing.

This module provides a pipeline architecture for processing research data
through discrete stages with clear input/output contracts.
"""

from .base import PipelineStage, StageResult
from .events import PipelineEvent, EventBus
from .context import PipelineContext
from .orchestrator import Pipeline

__all__ = [
    'PipelineStage',
    'StageResult',
    'PipelineEvent',
    'EventBus',
    'PipelineContext',
    'Pipeline',
]
