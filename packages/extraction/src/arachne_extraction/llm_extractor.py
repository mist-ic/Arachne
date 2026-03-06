"""
LLM-based structured extraction via instructor + LiteLLM.

The core extraction engine: send Markdown + a Pydantic schema to an LLM,
get back validated, typed JSON. Uses instructor for schema-bound extraction
with automatic retry/repair on validation failures.

Key design decisions:
    - LiteLLM as model abstraction (swap providers without code changes)
    - instructor for structured output enforcement (Pydantic validation)
    - Conditional reattempt on empty/NA results (inspired by ScrapeGraphAI)
    - Full extraction provenance tracking (model, tokens, cost, latency)

References:
    - Research.md §2.1: instructor consensus #1, LiteLLM normalization
    - RepoStudy §15: ScrapeGraphAI ConditionalNode pattern
    - Phase3.md Step 2: Schema-bound extraction
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import instructor
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class ExtractionOutput:
    """Full extraction result with provenance metadata.

    Tracks everything needed for cost analysis, model benchmarking,
    and extraction quality assessment.
    """

    data: Any  # The extracted Pydantic model instance
    model_used: str  # e.g., "gemini/gemini-2.5-flash"
    tokens_input: int = 0
    tokens_output: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    retry_count: int = 0
    reattempt_count: int = 0  # Conditional reattempts (different from retries)
    extraction_method: str = "llm"  # "llm", "vision", "auto_schema"
    confidence: float = 1.0  # 0-1, based on field completeness
    cascade_path: list[str] = field(default_factory=list)  # Models tried in order
    raw_response: str | None = None  # Raw LLM response for debugging


class ExtractionConfig(BaseModel):
    """Configuration for an extraction run."""

    model: str = Field(
        default="gemini/gemini-2.5-flash",
        description="LiteLLM model identifier",
    )
    max_retries: int = Field(default=3, ge=1, le=10)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=4096, ge=100)
    timeout_seconds: int = Field(default=60, ge=5)

    # Reattempt configuration (different prompt strategy on empty/NA)
    enable_reattempt: bool = True
    reattempt_model: str | None = None  # Escalate to different model
    max_reattempts: int = Field(default=2, ge=0, le=5)

    # API configuration
    api_key: str | None = None
    api_base: str | None = None  # For Ollama: "http://localhost:11434/v1"


# ============================================================================
# Prompt Templates
# ============================================================================


SYSTEM_PROMPT = """You are a precise data extraction assistant. Your task is to extract structured data from web page content according to the specified schema.

Rules:
1. ONLY include data that is EXPLICITLY present in the content
2. Do NOT infer, guess, or hallucinate values
3. If a field's value is not found in the content, return null for optional fields
4. For required fields, extract the best match available
5. Preserve the exact text as it appears (don't paraphrase or summarize)
6. For numeric fields, extract the number without currency symbols or units unless the schema specifies otherwise
7. For date fields, use ISO 8601 format when possible"""

EXTRACTION_USER_TEMPLATE = """Extract structured data from the following web page content.

--- PAGE CONTENT ---
{content}
--- END CONTENT ---

Extract the data according to the schema. Only include information explicitly present in the content above."""

REATTEMPT_SYSTEM_PROMPT = """You are a precise data extraction assistant performing a RETRY extraction. The previous attempt returned empty or NA values for critical fields, but the content likely contains the data.

Look more carefully this time:
1. Check for data in tables, lists, and structured sections
2. Look for data near headings that match field names
3. Consider that field values may be in unexpected formats
4. The data IS in the content — look harder

Rules remain the same: only extract explicitly present data, never hallucinate."""

REATTEMPT_USER_TEMPLATE = """The previous extraction attempt failed to find values for these fields: {missing_fields}

Here is the content again. Please look more carefully for the missing data.

--- PAGE CONTENT ---
{content}
--- END CONTENT ---

--- PAGE URL ---
{url}
--- END URL ---

Extract ALL fields according to the schema, paying special attention to the previously missing fields."""


# ============================================================================
# Cost Estimation
# ============================================================================


# Approximate pricing per million tokens (input / output) as of early 2026
# Updated regularly — these are ballpark estimates for cost tracking
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Gemini models
    "gemini/gemini-2.5-pro": (1.25, 10.0),
    "gemini/gemini-2.5-flash": (0.15, 0.60),
    "gemini/gemini-2.0-flash": (0.10, 0.40),
    # OpenAI models
    "openai/gpt-4o": (2.50, 10.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/o3-mini": (1.10, 4.40),
    # Anthropic models
    "anthropic/claude-sonnet-4-20250514": (3.0, 15.0),
    "anthropic/claude-haiku-3.5": (0.80, 4.0),
    # Local models (free)
    "ollama/qwen3:32b": (0.0, 0.0),
    "ollama/qwen3:8b": (0.0, 0.0),
    "ollama/llama4-scout": (0.0, 0.0),
    "ollama/phi-4": (0.0, 0.0),
    "ollama/gemma3:27b": (0.0, 0.0),
}


def _estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate the cost of an LLM call in USD."""
    # Try exact match first, then prefix match
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        for key, value in MODEL_PRICING.items():
            if model.startswith(key.split("/")[0]):
                pricing = value
                break

    if pricing is None:
        return 0.0

    cost_in, cost_out = pricing
    return (tokens_in * cost_in + tokens_out * cost_out) / 1_000_000


# ============================================================================
# LLM Extractor
# ============================================================================


class LLMExtractor:
    """Schema-bound LLM extraction engine.

    Uses instructor + LiteLLM to extract structured data from Markdown
    content into validated Pydantic models. Handles retry, repair,
    and conditional reattempt with model escalation.

    Usage:
        extractor = LLMExtractor(config=ExtractionConfig(
            model="gemini/gemini-2.5-flash",
            api_key="...",
        ))

        class Product(BaseModel):
            name: str
            price: float
            description: str | None = None

        result = await extractor.extract(
            markdown="# Product Page\\nWidget Pro - $29.99\\nA great widget.",
            schema=Product,
        )
        print(result.data)  # Product(name='Widget Pro', price=29.99, ...)
    """

    def __init__(self, config: ExtractionConfig | None = None):
        self.config = config or ExtractionConfig()
        self._client = self._create_client()

    def _create_client(self) -> instructor.Instructor:
        """Create an instructor-wrapped LiteLLM client."""
        import litellm

        # Configure LiteLLM
        if self.config.api_key:
            # Set provider-specific key based on model prefix
            model = self.config.model
            if model.startswith("gemini/"):
                litellm.api_key = self.config.api_key
            elif model.startswith("openai/"):
                litellm.api_key = self.config.api_key
            elif model.startswith("anthropic/"):
                litellm.api_key = self.config.api_key

        if self.config.api_base:
            litellm.api_base = self.config.api_base

        # Create instructor client with LiteLLM
        return instructor.from_litellm(litellm.completion)

    async def extract(
        self,
        markdown: str,
        schema: type[T],
        *,
        url: str | None = None,
        extra_context: str | None = None,
    ) -> ExtractionOutput:
        """Extract structured data from markdown using an LLM.

        This is the primary extraction method. Sends the markdown content
        and Pydantic schema to the LLM, validates the response, and
        retries on validation failure.

        Args:
            markdown: Preprocessed markdown content.
            schema: Pydantic model class defining the extraction target.
            url: Source URL for context (helps LLM understand the page).
            extra_context: Additional context to include in the prompt.

        Returns:
            ExtractionOutput with extracted data and full provenance.
        """
        start_time = time.monotonic()
        cascade_path = [self.config.model]

        try:
            # Primary extraction attempt
            result, usage = await self._call_llm(
                markdown=markdown,
                schema=schema,
                model=self.config.model,
                system_prompt=SYSTEM_PROMPT,
                user_template=EXTRACTION_USER_TEMPLATE,
                url=url,
            )

            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            retry_count = usage.get("retry_count", 0)

            # Check for empty/NA results and reattempt if configured
            reattempt_count = 0
            if self.config.enable_reattempt and result is not None:
                missing = _find_missing_fields(result)
                if missing and reattempt_count < self.config.max_reattempts:
                    logger.info(
                        "extraction_reattempt",
                        missing_fields=missing,
                        model=self.config.model,
                    )
                    reattempt_model = self.config.reattempt_model or self.config.model
                    cascade_path.append(f"{reattempt_model}(reattempt)")

                    reattempt_result, reattempt_usage = await self._call_llm(
                        markdown=markdown,
                        schema=schema,
                        model=reattempt_model,
                        system_prompt=REATTEMPT_SYSTEM_PROMPT,
                        user_template=REATTEMPT_USER_TEMPLATE,
                        url=url,
                        missing_fields=", ".join(missing),
                    )

                    if reattempt_result is not None:
                        new_missing = _find_missing_fields(reattempt_result)
                        if len(new_missing) < len(missing):
                            result = reattempt_result
                            tokens_in += reattempt_usage.get("prompt_tokens", 0)
                            tokens_out += reattempt_usage.get("completion_tokens", 0)
                    reattempt_count += 1

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            confidence = _calculate_confidence(result) if result else 0.0

            return ExtractionOutput(
                data=result,
                model_used=self.config.model,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                estimated_cost_usd=_estimate_cost(self.config.model, tokens_in, tokens_out),
                latency_ms=elapsed_ms,
                retry_count=retry_count,
                reattempt_count=reattempt_count,
                extraction_method="llm",
                confidence=confidence,
                cascade_path=cascade_path,
            )

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "extraction_failed",
                model=self.config.model,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )
            return ExtractionOutput(
                data=None,
                model_used=self.config.model,
                latency_ms=elapsed_ms,
                confidence=0.0,
                cascade_path=cascade_path,
                raw_response=str(e),
            )

    async def _call_llm(
        self,
        markdown: str,
        schema: type[T],
        model: str,
        system_prompt: str,
        user_template: str,
        url: str | None = None,
        missing_fields: str | None = None,
    ) -> tuple[T | None, dict]:
        """Make a single LLM call with instructor schema enforcement.

        Returns the extracted model instance and usage statistics.
        """
        # Format the user prompt
        user_content = user_template.format(
            content=markdown,
            url=url or "unknown",
            missing_fields=missing_fields or "",
        )

        logger.debug(
            "llm_call_start",
            model=model,
            schema=schema.__name__,
            content_len=len(markdown),
        )

        # Use instructor to make the schema-bound call
        # instructor handles retry and validation internally
        result = self._client.chat.completions.create(
            model=model,
            response_model=schema,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            max_retries=self.config.max_retries,
        )

        # Extract usage from the response
        # instructor stores usage in _raw_response when available
        usage: dict = {}
        if hasattr(result, "_raw_response"):
            raw = result._raw_response
            if hasattr(raw, "usage"):
                usage = {
                    "prompt_tokens": getattr(raw.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(raw.usage, "completion_tokens", 0),
                }

        logger.debug(
            "llm_call_complete",
            model=model,
            schema=schema.__name__,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )

        return result, usage


# ============================================================================
# Confidence and Completeness Checks
# ============================================================================


def _find_missing_fields(result: BaseModel) -> list[str]:
    """Find fields that are None, empty, or NA in the extraction result.

    These are candidates for reattempt with a different strategy.
    """
    missing = []
    for field_name, field_info in result.model_fields.items():
        value = getattr(result, field_name, None)

        if value is None:
            # Only flag required fields as missing
            if field_info.is_required():
                missing.append(field_name)
            continue

        # Check for NA/empty string values
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in ("", "na", "n/a", "none", "null", "unknown", "-"):
                missing.append(field_name)
        elif isinstance(value, list) and len(value) == 0:
            missing.append(field_name)

    return missing


def _calculate_confidence(result: BaseModel) -> float:
    """Calculate extraction confidence based on field completeness.

    1.0 = all fields populated with non-empty values
    0.0 = no fields populated
    """
    if result is None:
        return 0.0

    total_fields = len(result.model_fields)
    if total_fields == 0:
        return 1.0

    populated = 0
    for field_name in result.model_fields:
        value = getattr(result, field_name, None)
        if value is not None:
            if isinstance(value, str) and value.strip().lower() in ("", "na", "n/a"):
                continue
            populated += 1

    return populated / total_fields
