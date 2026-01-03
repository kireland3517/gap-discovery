"""
Base classes for pipeline stages.

Each stage has clear input/output contracts and emits events for progress tracking.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


class StageStatus(Enum):
    """Status of a pipeline stage execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """Result of a pipeline stage execution."""
    status: StageStatus
    data: Any = None
    error: Optional[Exception] = None
    metrics: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == StageStatus.COMPLETED

    @property
    def failed(self) -> bool:
        return self.status == StageStatus.FAILED


class PipelineStage(ABC):
    """
    Abstract base class for pipeline stages.

    Each stage:
    - Validates its input before processing
    - Executes its core logic
    - Validates its output after processing
    - Emits events for progress tracking
    """

    def __init__(self, name: Optional[str] = None):
        self._name = name or self.__class__.__name__
        self._status = StageStatus.PENDING

    @property
    def name(self) -> str:
        """Human-readable name for this stage."""
        return self._name

    @property
    def status(self) -> StageStatus:
        """Current status of this stage."""
        return self._status

    @abstractmethod
    def validate_input(self, context: 'PipelineContext') -> bool:
        """
        Validate that the context has required input for this stage.

        Args:
            context: The pipeline context containing input data

        Returns:
            True if input is valid, False otherwise
        """
        pass

    @abstractmethod
    def validate_output(self, context: 'PipelineContext', result: StageResult) -> bool:
        """
        Validate that the stage produced expected output.

        Args:
            context: The pipeline context
            result: The result from execute()

        Returns:
            True if output is valid, False otherwise
        """
        pass

    @abstractmethod
    async def execute(self, context: 'PipelineContext') -> StageResult:
        """
        Execute the stage's core logic.

        Args:
            context: The pipeline context with input data

        Returns:
            StageResult with output data or error
        """
        pass

    async def run(self, context: 'PipelineContext') -> StageResult:
        """
        Run the full stage lifecycle: validate input, execute, validate output.

        This is the main entry point for running a stage.
        """
        self._status = StageStatus.RUNNING

        # Validate input
        if not self.validate_input(context):
            self._status = StageStatus.FAILED
            return StageResult(
                status=StageStatus.FAILED,
                error=ValueError(f"Input validation failed for stage {self.name}")
            )

        # Execute
        try:
            result = await self.execute(context)
        except Exception as e:
            self._status = StageStatus.FAILED
            return StageResult(
                status=StageStatus.FAILED,
                error=e
            )

        # Validate output
        if result.success and not self.validate_output(context, result):
            self._status = StageStatus.FAILED
            return StageResult(
                status=StageStatus.FAILED,
                error=ValueError(f"Output validation failed for stage {self.name}")
            )

        self._status = result.status
        return result

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, status={self.status.value})"
