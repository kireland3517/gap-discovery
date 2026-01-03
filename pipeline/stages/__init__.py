"""
Pipeline stages for research processing.

Each stage handles a specific phase of the research pipeline:
- ScrapeStage: Collect data from various platforms
- ValidationStage: Validate pain evidence using AI
- SynthesisStage: Synthesize themes from evidence
- ClusteringStage: Cluster patterns from themes
"""

from .scrape_stage import ScrapeStage
from .validation_stage import ValidationStage
from .synthesis_stage import SynthesisStage
from .clustering_stage import ClusteringStage

__all__ = [
    'ScrapeStage',
    'ValidationStage',
    'SynthesisStage',
    'ClusteringStage',
]
