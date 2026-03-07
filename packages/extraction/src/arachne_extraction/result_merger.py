"""
Multi-modal result merging for HTML + Vision extraction.

When both HTML-based and vision-based extraction produce results, this
module merges them field-by-field to produce the most complete and accurate
output. This multi-modal validation demonstrates a self-reinforcing
extraction pipeline.

Merge strategy:
    - Use HTML values when they match vision values (higher precision)
    - Use vision values for fields missing from HTML extraction
    - Flag conflicts for logging/review (both extracted different values)

References:
    - Research.md §2.2: Vision extraction cross-validation
    - Phase4.md Step 1.3: Result merging
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog
from pydantic import BaseModel

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class FieldSource(str, Enum):
    """Where a field's value came from in the merged result."""

    HTML = "html"
    VISION = "vision"
    AGREED = "agreed"  # Both sources returned the same value
    CONFLICT_HTML = "conflict_html"  # Conflict resolved in favor of HTML
    CONFLICT_VISION = "conflict_vision"  # Conflict resolved in favor of vision


@dataclass
class FieldMergeDetail:
    """Detailed merge information for a single field."""

    field_name: str
    source: FieldSource
    html_value: Any = None
    vision_value: Any = None
    merged_value: Any = None
    conflict: bool = False


@dataclass
class MergeResult:
    """Complete merge result with provenance tracking.

    Provides full transparency into how each field was resolved,
    enabling audit trails and quality assessment.
    """

    merged_data: BaseModel | None  # The final merged Pydantic model
    fields_from_html: int = 0
    fields_from_vision: int = 0
    fields_agreed: int = 0
    fields_conflicted: int = 0
    total_fields: int = 0
    merge_confidence: float = 0.0
    field_details: list[FieldMergeDetail] = field(default_factory=list)

    @property
    def agreement_ratio(self) -> float:
        """Fraction of fields where HTML and vision agreed."""
        if self.total_fields == 0:
            return 1.0
        return self.fields_agreed / self.total_fields


class MergeConfig(BaseModel):
    """Configuration for the merge strategy."""

    # When both sources provide a value, prefer HTML (higher precision)
    # unless vision confidence significantly exceeds HTML confidence
    prefer_html_on_conflict: bool = True

    # Similarity threshold for string comparison (fuzzy matching)
    string_similarity_threshold: float = 0.85

    # Numeric tolerance for considering values "the same"
    numeric_tolerance: float = 0.01


# ============================================================================
# Result Merger
# ============================================================================


class ResultMerger:
    """Merge HTML and vision extraction results field-by-field.

    Implements a multi-modal validation strategy that combines the
    strengths of both extraction methods:
    - HTML extraction: higher precision, exact text, structured data
    - Vision extraction: resilient to DOM obfuscation, captures visual data

    Usage:
        merger = ResultMerger()

        merged = merger.merge(
            html_result=html_product,   # Product(name="Widget", price=29.99)
            vision_result=vision_product, # Product(name="Widget", price=None, image_url="...")
            schema=Product,
        )

        print(merged.merged_data)     # Product(name="Widget", price=29.99, image_url="...")
        print(merged.fields_agreed)    # 1 (name matched)
        print(merged.fields_from_html) # 1 (price from HTML only)
        print(merged.fields_from_vision) # 1 (image_url from vision only)
    """

    def __init__(self, config: MergeConfig | None = None):
        self.config = config or MergeConfig()

    def merge(
        self,
        html_result: BaseModel | None,
        vision_result: BaseModel | None,
        schema: type[BaseModel],
        *,
        html_confidence: float = 1.0,
        vision_confidence: float = 1.0,
    ) -> MergeResult:
        """Merge HTML and vision extraction results.

        Args:
            html_result: Extraction from HTML/Markdown pipeline (may be None).
            vision_result: Extraction from vision pipeline (may be None).
            schema: The Pydantic model class to produce.
            html_confidence: Confidence score from HTML extraction.
            vision_confidence: Confidence score from vision extraction.

        Returns:
            MergeResult with the merged model and field-level provenance.
        """
        # Handle cases where one or both are missing
        if html_result is None and vision_result is None:
            return MergeResult(merged_data=None, merge_confidence=0.0)

        if html_result is None:
            return self._single_source_result(vision_result, schema, FieldSource.VISION)

        if vision_result is None:
            return self._single_source_result(html_result, schema, FieldSource.HTML)

        # Both results available — merge field by field
        merged_values: dict[str, Any] = {}
        details: list[FieldMergeDetail] = []
        fields_from_html = 0
        fields_from_vision = 0
        fields_agreed = 0
        fields_conflicted = 0

        for field_name in schema.model_fields:
            html_val = getattr(html_result, field_name, None)
            vision_val = getattr(vision_result, field_name, None)

            html_empty = self._is_empty(html_val)
            vision_empty = self._is_empty(vision_val)

            detail = FieldMergeDetail(
                field_name=field_name,
                html_value=html_val,
                vision_value=vision_val,
                source=FieldSource.HTML,
            )

            if html_empty and vision_empty:
                # Neither source has a value
                merged_values[field_name] = None
                detail.source = FieldSource.HTML
                detail.merged_value = None
            elif html_empty and not vision_empty:
                # Only vision has a value
                merged_values[field_name] = vision_val
                detail.source = FieldSource.VISION
                detail.merged_value = vision_val
                fields_from_vision += 1
            elif not html_empty and vision_empty:
                # Only HTML has a value
                merged_values[field_name] = html_val
                detail.source = FieldSource.HTML
                detail.merged_value = html_val
                fields_from_html += 1
            else:
                # Both have values — compare
                if self._values_match(html_val, vision_val):
                    # Agreement — use HTML (higher precision)
                    merged_values[field_name] = html_val
                    detail.source = FieldSource.AGREED
                    detail.merged_value = html_val
                    fields_agreed += 1
                else:
                    # Conflict — resolve based on strategy
                    detail.conflict = True
                    fields_conflicted += 1

                    if self.config.prefer_html_on_conflict:
                        merged_values[field_name] = html_val
                        detail.source = FieldSource.CONFLICT_HTML
                        detail.merged_value = html_val
                    else:
                        merged_values[field_name] = vision_val
                        detail.source = FieldSource.CONFLICT_VISION
                        detail.merged_value = vision_val

                    logger.info(
                        "merge_conflict",
                        field=field_name,
                        html_value=str(html_val)[:100],
                        vision_value=str(vision_val)[:100],
                        resolution=detail.source.value,
                    )

            details.append(detail)

        # Build the merged model
        try:
            merged_model = schema.model_validate(merged_values)
        except Exception as e:
            logger.error("merge_validation_failed", error=str(e))
            # Fallback to HTML result on merge failure
            merged_model = html_result

        total_fields = len(schema.model_fields)
        populated = sum(1 for v in merged_values.values() if not self._is_empty(v))
        merge_confidence = populated / total_fields if total_fields > 0 else 0.0

        # Boost confidence when sources agree
        if fields_agreed > 0:
            agreement_boost = 0.1 * (fields_agreed / total_fields)
            merge_confidence = min(1.0, merge_confidence + agreement_boost)

        return MergeResult(
            merged_data=merged_model,
            fields_from_html=fields_from_html,
            fields_from_vision=fields_from_vision,
            fields_agreed=fields_agreed,
            fields_conflicted=fields_conflicted,
            total_fields=total_fields,
            merge_confidence=merge_confidence,
            field_details=details,
        )

    def _single_source_result(
        self,
        result: BaseModel,
        schema: type[BaseModel],
        source: FieldSource,
    ) -> MergeResult:
        """Create a MergeResult from a single extraction source."""
        details = []
        populated = 0

        for field_name in schema.model_fields:
            val = getattr(result, field_name, None)
            is_empty = self._is_empty(val)

            details.append(FieldMergeDetail(
                field_name=field_name,
                source=source,
                html_value=val if source == FieldSource.HTML else None,
                vision_value=val if source == FieldSource.VISION else None,
                merged_value=val,
            ))

            if not is_empty:
                populated += 1

        total = len(schema.model_fields)
        return MergeResult(
            merged_data=result,
            fields_from_html=populated if source == FieldSource.HTML else 0,
            fields_from_vision=populated if source == FieldSource.VISION else 0,
            total_fields=total,
            merge_confidence=populated / total if total > 0 else 0.0,
            field_details=details,
        )

    def _values_match(self, val_a: Any, val_b: Any) -> bool:
        """Check if two values are equivalent (with tolerance for fuzzy matching)."""
        if val_a == val_b:
            return True

        # String comparison with normalization
        if isinstance(val_a, str) and isinstance(val_b, str):
            a_norm = val_a.strip().lower()
            b_norm = val_b.strip().lower()
            if a_norm == b_norm:
                return True
            # Fuzzy match using simple character overlap ratio
            return self._string_similarity(a_norm, b_norm) >= self.config.string_similarity_threshold

        # Numeric comparison with tolerance
        if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
            if val_a == 0 and val_b == 0:
                return True
            max_val = max(abs(val_a), abs(val_b))
            if max_val == 0:
                return True
            return abs(val_a - val_b) / max_val <= self.config.numeric_tolerance

        return False

    @staticmethod
    def _string_similarity(a: str, b: str) -> float:
        """Simple character-level similarity ratio (Dice coefficient).

        Fast approximation — no external dependency needed.
        """
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0

        # Character bigrams
        bigrams_a = {a[i : i + 2] for i in range(len(a) - 1)}
        bigrams_b = {b[i : i + 2] for i in range(len(b) - 1)}

        if not bigrams_a and not bigrams_b:
            return 1.0 if a == b else 0.0

        intersection = len(bigrams_a & bigrams_b)
        return 2.0 * intersection / (len(bigrams_a) + len(bigrams_b))

    @staticmethod
    def _is_empty(value: Any) -> bool:
        """Check if a value is effectively empty/missing."""
        if value is None:
            return True
        if isinstance(value, str):
            normalized = value.strip().lower()
            return normalized in ("", "na", "n/a", "none", "null", "unknown", "-")
        if isinstance(value, list):
            return len(value) == 0
        return False
