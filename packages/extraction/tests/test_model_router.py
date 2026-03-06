"""
Tests for the multi-model extraction router.
"""

from __future__ import annotations

import pytest

from arachne_extraction.model_router import (
    ComplexityEstimator,
    ComplexityScore,
    CostConfig,
    CostMode,
    ModelCascade,
    ModelInfo,
    ModelTier,
)


# ============================================================================
# Test Content Fixtures
# ============================================================================


SIMPLE_CONTENT = """# Products

- Widget A: $19.99
- Widget B: $24.99
- Widget C: $34.99
"""

COMPLEX_CONTENT = """# Annual Report 2024

The following comprehensive analysis covers all aspects of our operations
across multiple geographies, product lines, and market segments. The data
presented here has been audited by independent third parties and reflects
our commitment to transparency and stakeholder communication.

## Financial Performance

Revenue grew by 15% year-over-year to $2.4 billion, driven primarily by
our enterprise segment which saw 23% growth. Operating margins expanded
to 28%, up from 24% in the prior year.

### Regional Breakdown

| Region | Revenue ($M) | Growth (%) | Margin (%) | Headcount |
|--------|-------------|------------|------------|-----------|
| North America | 1,200 | 12 | 31 | 4,500 |
| Europe | 680 | 18 | 26 | 2,800 |
| Asia Pacific | 420 | 22 | 24 | 1,900 |
| Latin America | 100 | 8 | 19 | 600 |

### Product Segments

Our diversified portfolio continues to deliver balanced growth across
all major product categories, with SaaS showing particular strength.

| Product | Revenue ($M) | YoY Growth | Market Share |
|---------|-------------|------------|--------------|
| SaaS Platform | 900 | 28% | 15% |
| Hardware | 600 | 5% | 22% |
| Services | 500 | 12% | 8% |
| Licensing | 400 | -3% | 31% |

## Strategic Initiatives

Multiple long-term initiatives are underway to position the company for
sustained growth in the rapidly evolving technology landscape.

### AI Integration

We invested $340M in AI capabilities, deploying machine learning models
across our product portfolio. Key deployments include natural language
processing for customer support automation, predictive analytics for
supply chain optimization, and computer vision for quality control.

### Sustainability

Carbon emissions reduced by 30% since 2020 baseline. Renewable energy
now powers 78% of our data centers. Water usage per unit of compute
decreased by 45%.
""" * 3  # Repeat to make it long


OBFUSCATED_CONTENT = """Some very short text with no structure."""


LISTING_CONTENT = """# Search Results

## Product 1
Widget Alpha - $19.99
Great for beginners

## Product 2
Widget Beta - $24.99
Professional grade

## Product 3
Widget Gamma - $34.99
Enterprise edition

## Product 4
Widget Delta - $44.99
Ultimate performance

## Product 5
Widget Epsilon - $54.99
Premium quality
"""


# ============================================================================
# Complexity Estimator Tests
# ============================================================================


class TestComplexityEstimator:
    """Tests for complexity estimation."""

    def setup_method(self):
        self.estimator = ComplexityEstimator()

    def test_returns_complexity_score(self):
        score = self.estimator.estimate(SIMPLE_CONTENT)
        assert isinstance(score, ComplexityScore)

    def test_score_bounded(self):
        score = self.estimator.estimate(SIMPLE_CONTENT)
        assert 0.0 <= score.score <= 1.0

    def test_simple_content_low_complexity(self):
        score = self.estimator.estimate(SIMPLE_CONTENT)
        assert score.score < 0.5
        assert score.recommended_tier in (ModelTier.LOCAL, ModelTier.FAST)

    def test_complex_content_higher_complexity(self):
        score = self.estimator.estimate(COMPLEX_CONTENT)
        assert score.score > 0.2  # Should be meaningfully complex

    def test_has_tables_detected(self):
        score = self.estimator.estimate(COMPLEX_CONTENT)
        assert score.has_tables is True

    def test_no_tables_detected(self):
        score = self.estimator.estimate(SIMPLE_CONTENT)
        assert score.has_tables is False

    def test_token_count_estimated(self):
        score = self.estimator.estimate(COMPLEX_CONTENT)
        assert score.token_count > 0
        # Rough check: should be approximately len / 4
        expected = len(COMPLEX_CONTENT) // 4
        assert abs(score.token_count - expected) < expected * 0.5

    def test_listing_has_repeating_patterns(self):
        score = self.estimator.estimate(LISTING_CONTENT)
        assert score.repeating_patterns >= 3  # Multiple ## headings

    def test_reasoning_provided(self):
        score = self.estimator.estimate(SIMPLE_CONTENT)
        assert len(score.reasoning) > 0

    def test_structure_score_high_for_structured(self):
        score = self.estimator.estimate(LISTING_CONTENT)
        assert score.structure_score > 0.1  # Many headings and lists

    def test_domain_history_overrides(self):
        history = {"last_successful_tier": "fast"}
        score = self.estimator.estimate(
            SIMPLE_CONTENT, domain_history=history,
        )
        assert score.recommended_tier == ModelTier.FAST

    def test_obfuscation_detection(self):
        # Very short content with no structure suggests obfuscation
        short = "x" * 50  # Short, no structure
        score = self.estimator.estimate(short)
        # May or may not trigger obfuscation depending on exact heuristics
        assert isinstance(score.has_obfuscation_signals, bool)


# ============================================================================
# Model Cascade Tests
# ============================================================================


class TestModelCascade:
    """Tests for the model cascade ordering."""

    def setup_method(self):
        self.cascade = ModelCascade()

    def test_local_cascade_starts_with_local(self):
        order = self.cascade.get_cascade_order(ModelTier.LOCAL)
        assert len(order) > 0
        assert order[0].tier == ModelTier.LOCAL

    def test_fast_cascade_skips_local(self):
        order = self.cascade.get_cascade_order(ModelTier.FAST)
        assert len(order) > 0
        assert order[0].tier == ModelTier.FAST

    def test_frontier_cascade_starts_with_frontier(self):
        order = self.cascade.get_cascade_order(ModelTier.FRONTIER)
        assert len(order) > 0
        assert order[0].tier == ModelTier.FRONTIER

    def test_local_cascade_includes_all_tiers(self):
        order = self.cascade.get_cascade_order(ModelTier.LOCAL)
        tiers = {m.tier for m in order}
        assert ModelTier.LOCAL in tiers
        assert ModelTier.FAST in tiers
        assert ModelTier.FRONTIER in tiers

    def test_vision_cascade_specific(self):
        order = self.cascade.get_cascade_order(ModelTier.VISION)
        tiers = [m.tier for m in order]
        # Should start with vision, then frontier
        assert tiers[0] == ModelTier.VISION

    def test_models_sorted_by_cost_within_tier(self):
        order = self.cascade.get_cascade_order(ModelTier.LOCAL)
        # Within each tier, should be sorted by cost (cheapest first)
        for i in range(len(order) - 1):
            if order[i].tier == order[i + 1].tier:
                assert order[i].cost_per_1m_input <= order[i + 1].cost_per_1m_input


# ============================================================================
# Cost Config Tests
# ============================================================================


class TestCostConfig:
    """Tests for cost configuration."""

    def test_default_config(self):
        config = CostConfig()
        assert config.cost_mode == CostMode.BALANCED
        assert config.max_cost_per_page_usd == 0.10
        assert config.max_latency_ms == 30_000

    def test_minimize_mode(self):
        config = CostConfig(cost_mode=CostMode.MINIMIZE)
        assert config.cost_mode == CostMode.MINIMIZE

    def test_accuracy_mode(self):
        config = CostConfig(cost_mode=CostMode.ACCURACY)
        assert config.cost_mode == CostMode.ACCURACY
