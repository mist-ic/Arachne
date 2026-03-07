"""
Change detection subpackage — monitors websites for content changes.

Provides multi-signal change detection combining DOM differencing,
embedding similarity, visual diffing, and entity-level comparison.

Modules:
    dom_differ           — Structural DOM tree edit distance
    embedding_similarity — Semantic content similarity
    visual_differ        — Perceptual image hashing + SSIM
    entity_differ        — Extracted data deep diff
    aggregator           — Signal aggregation and scoring
"""

from arachne_extraction.change.dom_differ import DOMDiffer
from arachne_extraction.change.embedding_similarity import EmbeddingSimilarity
from arachne_extraction.change.visual_differ import VisualDiffer
from arachne_extraction.change.entity_differ import EntityDiffer
from arachne_extraction.change.aggregator import ChangeAggregator

__all__ = [
    "DOMDiffer",
    "EmbeddingSimilarity",
    "VisualDiffer",
    "EntityDiffer",
    "ChangeAggregator",
]
