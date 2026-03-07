"""
Multi-signal change aggregation and scoring.

Combines all change detection signals (DOM, embedding, visual, entity)
into a single 0-1 change score with categorical severity labels.
Provides a unified interface for the change monitoring workflow.

References:
    - Phase4.md Step 4.5: Aggregation engine
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from arachne_extraction.change.dom_differ import DOMDiffer, DOMDiffResult
from arachne_extraction.change.embedding_similarity import (
    EmbeddingSimilarity,
    EmbeddingSimilarityResult,
)
from arachne_extraction.change.entity_differ import EntityDiffer, EntityDiffResult
from arachne_extraction.change.visual_differ import VisualDiffer, VisualDiffResult

logger = structlog.get_logger(__name__)


class ChangeCategory(str, Enum):
    """Categorical change classification."""

    NO_CHANGE = "no_change"
    CONTENT_UPDATE = "content_update"  # Data changed, structure same
    LAYOUT_CHANGE = "layout_change"  # Structure changed, data similar
    MAJOR_REDESIGN = "major_redesign"  # Both structure and content changed
    NEW_CONTENT = "new_content"  # New entities appeared


@dataclass
class ChangeScore:
    """Aggregated change score with per-signal breakdown."""

    overall: float  # 0-1, where 0 = no change, 1 = completely different
    category: ChangeCategory
    dom_change: float = 0.0  # 0-1
    semantic_change: float = 0.0  # 0-1
    visual_change: float = 0.0  # 0-1
    entity_change: float = 0.0  # 0-1
    signals_available: int = 0
    dom_result: DOMDiffResult | None = None
    semantic_result: EmbeddingSimilarityResult | None = None
    visual_result: VisualDiffResult | None = None
    entity_result: EntityDiffResult | None = None


class ChangeAggregatorConfig:
    """Configuration for signal weights and thresholds."""

    def __init__(
        self,
        dom_weight: float = 0.25,
        semantic_weight: float = 0.25,
        visual_weight: float = 0.25,
        entity_weight: float = 0.25,
        no_change_threshold: float = 0.10,
        major_change_threshold: float = 0.60,
    ):
        self.dom_weight = dom_weight
        self.semantic_weight = semantic_weight
        self.visual_weight = visual_weight
        self.entity_weight = entity_weight
        self.no_change_threshold = no_change_threshold
        self.major_change_threshold = major_change_threshold


class ChangeAggregator:
    """Aggregate change detection signals into a unified score.

    Runs all available detection methods and combines their results
    into a single change score with categorical classification.

    Usage:
        aggregator = ChangeAggregator()

        score = aggregator.compute(
            html_old=old_html,
            html_new=new_html,
            text_old=old_markdown,
            text_new=new_markdown,
            data_old=old_entities,
            data_new=new_entities,
        )

        print(f"Change: {score.overall:.2f} ({score.category.value})")
    """

    def __init__(self, config: ChangeAggregatorConfig | None = None):
        self.config = config or ChangeAggregatorConfig()
        self.dom_differ = DOMDiffer()
        self.embedding_sim = EmbeddingSimilarity()
        self.visual_differ = VisualDiffer()
        self.entity_differ = EntityDiffer()

    def compute(
        self,
        *,
        html_old: str | None = None,
        html_new: str | None = None,
        text_old: str | None = None,
        text_new: str | None = None,
        screenshot_old: bytes | None = None,
        screenshot_new: bytes | None = None,
        data_old: dict | list[dict] | None = None,
        data_new: dict | list[dict] | None = None,
    ) -> ChangeScore:
        """Compute aggregated change score from all available signals.

        Pass whichever signals are available — the aggregator adapts
        weights based on which signals were computed.
        """
        signals: dict[str, float] = {}
        results: dict[str, Any] = {}

        # DOM differencing
        if html_old is not None and html_new is not None:
            dom_result = self.dom_differ.diff(html_old, html_new)
            signals["dom"] = dom_result.structural_distance
            results["dom"] = dom_result

        # Semantic similarity
        if text_old is not None and text_new is not None:
            sem_result = self.embedding_sim.compare(text_old, text_new)
            signals["semantic"] = 1.0 - sem_result.similarity
            results["semantic"] = sem_result

        # Visual comparison
        if screenshot_old is not None and screenshot_new is not None:
            vis_result = self.visual_differ.compare(screenshot_old, screenshot_new)
            signals["visual"] = 1.0 - vis_result.similarity
            results["visual"] = vis_result

        # Entity comparison
        if data_old is not None and data_new is not None:
            ent_result = self.entity_differ.compare(data_old, data_new)
            signals["entity"] = 1.0 - ent_result.similarity
            results["entity"] = ent_result

        if not signals:
            return ChangeScore(
                overall=0.0,
                category=ChangeCategory.NO_CHANGE,
            )

        # Compute weighted average with dynamic weight normalization
        weight_map = {
            "dom": self.config.dom_weight,
            "semantic": self.config.semantic_weight,
            "visual": self.config.visual_weight,
            "entity": self.config.entity_weight,
        }

        total_weight = sum(weight_map[k] for k in signals)
        overall = sum(
            signals[k] * weight_map[k] for k in signals
        ) / total_weight if total_weight > 0 else 0.0

        # Classify the change
        category = self._classify(
            overall=overall,
            dom_change=signals.get("dom", 0),
            semantic_change=signals.get("semantic", 0),
            entity_change=signals.get("entity", 0),
        )

        return ChangeScore(
            overall=max(0.0, min(1.0, overall)),
            category=category,
            dom_change=signals.get("dom", 0),
            semantic_change=signals.get("semantic", 0),
            visual_change=signals.get("visual", 0),
            entity_change=signals.get("entity", 0),
            signals_available=len(signals),
            dom_result=results.get("dom"),
            semantic_result=results.get("semantic"),
            visual_result=results.get("visual"),
            entity_result=results.get("entity"),
        )

    def _classify(
        self,
        overall: float,
        dom_change: float,
        semantic_change: float,
        entity_change: float,
    ) -> ChangeCategory:
        """Classify the type of change based on signal patterns."""
        if overall < self.config.no_change_threshold:
            return ChangeCategory.NO_CHANGE

        if overall > self.config.major_change_threshold:
            return ChangeCategory.MAJOR_REDESIGN

        # Structure changed but content similar
        if dom_change > 0.4 and semantic_change < 0.3:
            return ChangeCategory.LAYOUT_CHANGE

        # Content changed but structure same
        if entity_change > 0.3 and dom_change < 0.2:
            return ChangeCategory.CONTENT_UPDATE

        # New content appeared
        if entity_change > 0.5:
            return ChangeCategory.NEW_CONTENT

        return ChangeCategory.CONTENT_UPDATE
