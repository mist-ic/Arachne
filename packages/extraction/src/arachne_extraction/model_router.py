"""
Multi-model extraction router with cost/accuracy tradeoffs.

Intelligently routes extraction requests to the optimal model based on
page complexity, token count, cost constraints, and accuracy requirements.
This is the ML systems engineering showcase — demonstrating production
ML pipeline economics, not just API calls.

Architecture:
    ComplexityEstimator → ExtractionRouter → ModelCascade → LLMExtractor

References:
    - Research.md §2.5: Multi-model routing recommendations
    - Phase3.md Step 3: Router design, complexity estimation, cascade
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

from arachne_extraction.llm_extractor import (
    ExtractionConfig,
    ExtractionOutput,
    LLMExtractor,
)

logger = structlog.get_logger(__name__)


# ============================================================================
# Configuration
# ============================================================================


class CostMode(StrEnum):
    """Cost optimization strategy for model selection."""

    MINIMIZE = "minimize"  # Always try local model first, escalate on failure
    BALANCED = "balanced"  # Route based on complexity estimator
    ACCURACY = "accuracy"  # Always use frontier model


class ModelTier(StrEnum):
    """Model capability tiers for the cascade."""

    LOCAL = "local"  # Ollama (free, GPU-bound)
    FAST = "fast"  # Gemini Flash, GPT-4o-mini (cheap, good)
    FRONTIER = "frontier"  # Gemini Pro, GPT-4o, Claude Sonnet (expensive, best)
    VISION = "vision"  # Vision models for obfuscated DOM


class CostConfig(BaseModel):
    """Cost and SLO configuration for extraction routing."""

    cost_mode: CostMode = CostMode.BALANCED
    max_cost_per_page_usd: float = Field(
        default=0.10,
        description="Hard cost ceiling per page extraction",
    )
    max_latency_ms: int = Field(
        default=30_000,
        description="Maximum acceptable extraction latency",
    )
    prefer_local: bool = Field(
        default=True,
        description="Prefer local models when complexity allows",
    )


# ============================================================================
# Model Registry
# ============================================================================


@dataclass
class ModelInfo:
    """Metadata about a model for routing decisions."""

    model_id: str  # LiteLLM model identifier
    tier: ModelTier
    context_window: int  # Max input tokens
    cost_per_1m_input: float  # USD per million input tokens
    cost_per_1m_output: float  # USD per million output tokens
    avg_latency_ms: int  # Approximate latency for typical extraction
    supports_structured_output: bool = True
    supports_vision: bool = False
    requires_gpu: bool = False
    description: str = ""


# Default model registry — can be extended via configuration
DEFAULT_MODELS: dict[str, ModelInfo] = {
    # Local models (free, requires GPU, Ollama)
    "ollama/qwen3:32b": ModelInfo(
        model_id="ollama/qwen3:32b",
        tier=ModelTier.LOCAL,
        context_window=32_768,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        avg_latency_ms=3000,
        requires_gpu=True,
        description="Qwen3 32B — strong local extraction model",
    ),
    "ollama/qwen3:8b": ModelInfo(
        model_id="ollama/qwen3:8b",
        tier=ModelTier.LOCAL,
        context_window=32_768,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        avg_latency_ms=1500,
        requires_gpu=True,
        description="Qwen3 8B — fast local model for simple extractions",
    ),
    "ollama/gemma3:27b": ModelInfo(
        model_id="ollama/gemma3:27b",
        tier=ModelTier.LOCAL,
        context_window=128_000,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        avg_latency_ms=2500,
        requires_gpu=True,
        description="Gemma3 27B — Google's local model, 128K context",
    ),
    # Fast cloud models (cheap, good accuracy)
    "gemini/gemini-2.5-flash": ModelInfo(
        model_id="gemini/gemini-2.5-flash",
        tier=ModelTier.FAST,
        context_window=1_048_576,
        cost_per_1m_input=0.15,
        cost_per_1m_output=0.60,
        avg_latency_ms=2000,
        description="Gemini 2.5 Flash — excellent cost/accuracy ratio",
    ),
    "gemini/gemini-2.0-flash": ModelInfo(
        model_id="gemini/gemini-2.0-flash",
        tier=ModelTier.FAST,
        context_window=1_048_576,
        cost_per_1m_input=0.10,
        cost_per_1m_output=0.40,
        avg_latency_ms=1500,
        description="Gemini 2.0 Flash — cheapest cloud option",
    ),
    # Frontier models (best accuracy, expensive)
    "gemini/gemini-2.5-pro": ModelInfo(
        model_id="gemini/gemini-2.5-pro",
        tier=ModelTier.FRONTIER,
        context_window=1_048_576,
        cost_per_1m_input=1.25,
        cost_per_1m_output=10.0,
        avg_latency_ms=5000,
        description="Gemini 2.5 Pro — frontier accuracy for complex pages",
    ),
    # Vision models (for obfuscated DOM)
    "ollama/qwen3-vl:32b": ModelInfo(
        model_id="ollama/qwen3-vl:32b",
        tier=ModelTier.VISION,
        context_window=32_768,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        avg_latency_ms=4000,
        supports_vision=True,
        requires_gpu=True,
        description="Qwen3 VL 32B — local vision for CAPTCHA and visual extraction",
    ),
}


# ============================================================================
# Complexity Estimation
# ============================================================================


@dataclass
class ComplexityScore:
    """Result of page complexity estimation.

    Informs the router about what model tier is appropriate.
    """

    score: float  # 0.0 (trivial) to 1.0 (extremely complex)
    token_count: int  # Estimated token count
    structure_score: float  # 0-1, how structured the content is
    repeating_patterns: int  # Count of repeated entity patterns
    has_tables: bool  # Whether the content contains tables
    has_obfuscation_signals: bool  # DOM obfuscation detected
    recommended_tier: ModelTier  # Recommended model tier
    reasoning: str  # Human-readable explanation


class ComplexityEstimator:
    """Lightweight heuristic classifier for page complexity.

    Examines preprocessed Markdown to estimate extraction difficulty
    without calling any LLM. Used by the router to select the optimal
    model before making any API calls.
    """

    # Thresholds for tier selection
    LOCAL_MAX_TOKENS = 3000
    LOCAL_MAX_COMPLEXITY = 0.3
    FAST_MAX_TOKENS = 15000
    FAST_MAX_COMPLEXITY = 0.6
    # Above these → frontier

    def estimate(
        self,
        markdown: str,
        *,
        chars_per_token: float = 4.0,
        domain_history: dict | None = None,
    ) -> ComplexityScore:
        """Estimate the complexity of extracting data from this content.

        Factors:
            - Token count: more tokens = more complex
            - Structure score: tables/lists are easier than prose
            - Repeating patterns: listings are easier than single entities
            - Obfuscation signals: empty text, excessive nesting
            - Domain history: what model succeeded for this domain before

        Args:
            markdown: Preprocessed markdown content.
            chars_per_token: Character-to-token ratio.
            domain_history: Optional historical model performance for this domain.

        Returns:
            ComplexityScore with recommended model tier.
        """
        token_count = int(len(markdown) / chars_per_token)

        # Structure analysis
        structure_score = self._score_structure(markdown)
        repeating = self._count_repeating_patterns(markdown)
        has_tables = bool(re.search(r"^\|.*\|$", markdown, re.MULTILINE))
        has_obfuscation = self._detect_obfuscation(markdown)

        # Composite complexity score
        score = 0.0

        # Token count contribution (0-0.4)
        if token_count < 1000:
            score += 0.05
        elif token_count < 3000:
            score += 0.15
        elif token_count < 10000:
            score += 0.25
        else:
            score += 0.40

        # Structure contribution (inverse — more structured = less complex)
        score += (1.0 - structure_score) * 0.25

        # Repeating patterns (more repetition = simpler)
        if repeating > 5:
            score -= 0.10
        elif repeating > 2:
            score -= 0.05

        # Obfuscation signals
        if has_obfuscation:
            score += 0.25

        score = max(0.0, min(1.0, score))

        # Check domain history for model preference
        if domain_history:
            historical_tier = domain_history.get("last_successful_tier")
            if historical_tier:
                recommended = ModelTier(historical_tier)
                reasoning = f"Historical: {historical_tier} succeeded for this domain"
                return ComplexityScore(
                    score=score,
                    token_count=token_count,
                    structure_score=structure_score,
                    repeating_patterns=repeating,
                    has_tables=has_tables,
                    has_obfuscation_signals=has_obfuscation,
                    recommended_tier=recommended,
                    reasoning=reasoning,
                )

        # Determine recommended tier based on score
        if has_obfuscation:
            recommended = ModelTier.VISION
            reasoning = "Obfuscation signals detected — vision model recommended"
        elif score <= self.LOCAL_MAX_COMPLEXITY and token_count <= self.LOCAL_MAX_TOKENS:
            recommended = ModelTier.LOCAL
            reasoning = f"Low complexity ({score:.2f}), {token_count} tokens — local model sufficient"
        elif score <= self.FAST_MAX_COMPLEXITY and token_count <= self.FAST_MAX_TOKENS:
            recommended = ModelTier.FAST
            reasoning = f"Medium complexity ({score:.2f}), {token_count} tokens — fast cloud model"
        else:
            recommended = ModelTier.FRONTIER
            reasoning = f"High complexity ({score:.2f}), {token_count} tokens — frontier model needed"

        return ComplexityScore(
            score=score,
            token_count=token_count,
            structure_score=structure_score,
            repeating_patterns=repeating,
            has_tables=has_tables,
            has_obfuscation_signals=has_obfuscation,
            recommended_tier=recommended,
            reasoning=reasoning,
        )

    def _score_structure(self, markdown: str) -> float:
        """Score how structured the content is (0 = unstructured prose, 1 = highly structured).

        High structure (tables, lists, headings) means the content is easier
        to extract from — the data is already organized.
        """
        lines = markdown.split("\n")
        total = max(len(lines), 1)

        structured_lines = sum(
            1 for line in lines
            if (
                line.strip().startswith("#")        # Heading
                or line.strip().startswith("|")      # Table
                or line.strip().startswith("- ")     # Unordered list
                or line.strip().startswith("* ")     # Unordered list
                or re.match(r"^\d+\.\s", line.strip())  # Ordered list
            )
        )

        return min(structured_lines / total, 1.0)

    def _count_repeating_patterns(self, markdown: str) -> int:
        """Count repeating structural patterns (likely entity listings).

        E.g., product cards, search results — many similar sections indicate
        a listing page where extraction is repetitive (simpler per-entity).
        """
        # Count headings at the same level — repeated H3s usually mean listings
        headings_by_level: dict[int, int] = {}
        for match in re.finditer(r"^(#{1,6})\s+", markdown, re.MULTILINE):
            level = len(match.group(1))
            headings_by_level[level] = headings_by_level.get(level, 0) + 1

        # The most-repeated heading level indicates listing patterns
        if headings_by_level:
            return max(headings_by_level.values())
        return 0

    def _detect_obfuscation(self, markdown: str) -> bool:
        """Detect signals that the DOM was obfuscated.

        These indicate that HTML extraction may fail and vision-based
        extraction might be needed.
        """
        signals = [
            # Very low content-to-markup ratio (lots of HTML, little text)
            len(markdown.strip()) < 200 and "![" not in markdown,
            # Suspicious patterns that survived pruning
            bool(re.search(r"canvas|webgl|svg.*text", markdown, re.IGNORECASE)),
            # Content that's just numbers/codes (obfuscated text)
            bool(re.search(r"&#\d{4,};", markdown)),
        ]
        return any(signals)


# ============================================================================
# Model Cascade
# ============================================================================


@dataclass
class CascadeResult:
    """Result of a model cascade attempt."""

    output: ExtractionOutput
    cascade_path: list[str] = field(default_factory=list)
    total_attempts: int = 0
    final_model: str = ""
    all_failed: bool = False


class ModelCascade:
    """Cascading model fallback on extraction failure.

    When the first-choice model fails validation after retries, automatically
    tries the next model up in capability. Logs the cascade path for
    observability and benchmarking.

    Similar to the Evasion Router's escalation — start cheap, escalate on failure.
    """

    def __init__(
        self,
        models: dict[str, ModelInfo] | None = None,
        api_keys: dict[str, str] | None = None,
        ollama_base_url: str = "http://localhost:11434/v1",
    ):
        self.models = models or DEFAULT_MODELS
        self.api_keys = api_keys or {}
        self.ollama_base_url = ollama_base_url

    def get_cascade_order(self, start_tier: ModelTier) -> list[ModelInfo]:
        """Get the ordered list of models to try, starting from the given tier.

        Order: start_tier models → next tier up → ... → frontier
        Skips vision models unless explicitly starting from VISION tier.
        """
        tier_order = [ModelTier.LOCAL, ModelTier.FAST, ModelTier.FRONTIER]

        if start_tier == ModelTier.VISION:
            # Vision cascade: vision → frontier
            vision_models = [m for m in self.models.values() if m.tier == ModelTier.VISION]
            frontier_models = [m for m in self.models.values() if m.tier == ModelTier.FRONTIER]
            return vision_models + frontier_models

        start_idx = tier_order.index(start_tier) if start_tier in tier_order else 0

        cascade: list[ModelInfo] = []
        for tier in tier_order[start_idx:]:
            tier_models = [m for m in self.models.values() if m.tier == tier]
            # Sort within tier: cheapest first
            tier_models.sort(key=lambda m: m.cost_per_1m_input)
            cascade.extend(tier_models)

        return cascade

    async def execute(
        self,
        markdown: str,
        schema: type,
        start_tier: ModelTier,
        cost_config: CostConfig,
        *,
        url: str | None = None,
    ) -> CascadeResult:
        """Execute the model cascade until extraction succeeds.

        Tries models in order from the starting tier upward. Stops when:
        - Extraction succeeds with sufficient confidence
        - Cost ceiling is reached
        - All models exhausted

        Args:
            markdown: Preprocessed markdown content.
            schema: Pydantic model class for extraction.
            start_tier: Starting model tier.
            cost_config: Cost and SLO constraints.
            url: Source URL for context.

        Returns:
            CascadeResult with the best extraction output.
        """
        cascade_models = self.get_cascade_order(start_tier)
        cascade_path: list[str] = []
        total_cost = 0.0
        best_output: ExtractionOutput | None = None

        for model_info in cascade_models:
            # Check cost ceiling
            if total_cost >= cost_config.max_cost_per_page_usd:
                logger.warning(
                    "cascade_cost_ceiling",
                    total_cost=total_cost,
                    ceiling=cost_config.max_cost_per_page_usd,
                )
                break

            cascade_path.append(model_info.model_id)

            # Build config for this model
            config = ExtractionConfig(
                model=model_info.model_id,
                api_key=self._get_api_key(model_info),
                api_base=self.ollama_base_url if model_info.tier == ModelTier.LOCAL else None,
                max_retries=2,  # Fewer retries per model in cascade (escalate instead)
                enable_reattempt=False,  # Don't reattempt — cascade handles escalation
            )

            try:
                extractor = LLMExtractor(config=config)
                output = await extractor.extract(markdown, schema, url=url)

                total_cost += output.estimated_cost_usd
                output.cascade_path = cascade_path.copy()

                # Success: confidence above threshold
                if output.data is not None and output.confidence >= 0.5:
                    logger.info(
                        "cascade_success",
                        model=model_info.model_id,
                        confidence=output.confidence,
                        attempts=len(cascade_path),
                        total_cost=total_cost,
                    )
                    return CascadeResult(
                        output=output,
                        cascade_path=cascade_path,
                        total_attempts=len(cascade_path),
                        final_model=model_info.model_id,
                    )

                # Partial success — keep as best so far
                if best_output is None or (output.confidence > best_output.confidence):
                    best_output = output

                logger.info(
                    "cascade_escalation",
                    from_model=model_info.model_id,
                    confidence=output.confidence,
                    reason="low_confidence",
                )

            except Exception as e:
                logger.warning(
                    "cascade_model_failed",
                    model=model_info.model_id,
                    error=str(e),
                )
                continue

        # All models exhausted — return best result or failure
        if best_output is not None:
            best_output.cascade_path = cascade_path
            return CascadeResult(
                output=best_output,
                cascade_path=cascade_path,
                total_attempts=len(cascade_path),
                final_model=best_output.model_used,
                all_failed=best_output.confidence < 0.5,
            )

        # Complete failure
        return CascadeResult(
            output=ExtractionOutput(
                data=None,
                model_used="none",
                confidence=0.0,
                cascade_path=cascade_path,
            ),
            cascade_path=cascade_path,
            total_attempts=len(cascade_path),
            all_failed=True,
        )

    def _get_api_key(self, model_info: ModelInfo) -> str | None:
        """Get the appropriate API key for a model."""
        if model_info.tier == ModelTier.LOCAL:
            return None  # Ollama doesn't need keys

        # Map model prefix to API key name
        prefix = model_info.model_id.split("/")[0]
        key_map = {
            "gemini": "GEMINI_API_KEY",
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
        }
        key_name = key_map.get(prefix, "")
        return self.api_keys.get(key_name)


# ============================================================================
# Extraction Router (Main Entry Point)
# ============================================================================


class ExtractionRouter:
    """Intelligent extraction routing engine.

    Main entry point for extraction requests. Examines the content,
    estimates complexity, selects the optimal model, and executes
    extraction with cascade fallback.

    Usage:
        router = ExtractionRouter(
            cost_config=CostConfig(cost_mode="balanced"),
            api_keys={"GEMINI_API_KEY": "..."},
        )

        result = await router.extract(
            markdown="# Product\\nWidget - $29.99",
            schema=Product,
            url="https://shop.example.com/widget",
        )
    """

    def __init__(
        self,
        cost_config: CostConfig | None = None,
        models: dict[str, ModelInfo] | None = None,
        api_keys: dict[str, str] | None = None,
        ollama_base_url: str = "http://localhost:11434/v1",
    ):
        self.cost_config = cost_config or CostConfig()
        self.estimator = ComplexityEstimator()
        self.cascade = ModelCascade(
            models=models,
            api_keys=api_keys,
            ollama_base_url=ollama_base_url,
        )
        self._domain_history: dict[str, dict] = {}

    async def extract(
        self,
        markdown: str,
        schema: type,
        *,
        url: str | None = None,
        domain: str | None = None,
        force_tier: ModelTier | None = None,
    ) -> ExtractionOutput:
        """Route an extraction request to the optimal model.

        Args:
            markdown: Preprocessed markdown content.
            schema: Pydantic model class for extraction.
            url: Source URL for context.
            domain: Target domain (for history-based routing).
            force_tier: Override the router's decision with a specific tier.

        Returns:
            ExtractionOutput with extracted data and full provenance.
        """
        # Step 1: Estimate complexity
        domain_history = self._domain_history.get(domain, {}) if domain else {}
        complexity = self.estimator.estimate(
            markdown, domain_history=domain_history,
        )

        logger.info(
            "routing_extraction",
            complexity_score=complexity.score,
            token_count=complexity.token_count,
            recommended_tier=complexity.recommended_tier,
            reasoning=complexity.reasoning,
            cost_mode=self.cost_config.cost_mode,
            domain=domain,
        )

        # Step 2: Determine starting tier
        if force_tier:
            start_tier = force_tier
        elif self.cost_config.cost_mode == CostMode.MINIMIZE:
            start_tier = ModelTier.LOCAL
        elif self.cost_config.cost_mode == CostMode.ACCURACY:
            start_tier = ModelTier.FRONTIER
        else:
            start_tier = complexity.recommended_tier

        # Step 3: Execute cascade
        cascade_result = await self.cascade.execute(
            markdown=markdown,
            schema=schema,
            start_tier=start_tier,
            cost_config=self.cost_config,
            url=url,
        )

        # Step 4: Update domain history
        if domain and cascade_result.output.data is not None:
            self._domain_history[domain] = {
                "last_successful_tier": cascade_result.final_model,
                "last_complexity": complexity.score,
                "cascade_depth": cascade_result.total_attempts,
            }

        output = cascade_result.output
        output.extraction_method = "llm"

        logger.info(
            "extraction_routed",
            final_model=cascade_result.final_model,
            cascade_path=cascade_result.cascade_path,
            attempts=cascade_result.total_attempts,
            confidence=output.confidence,
            cost_usd=output.estimated_cost_usd,
            latency_ms=output.latency_ms,
            all_failed=cascade_result.all_failed,
        )

        return output
