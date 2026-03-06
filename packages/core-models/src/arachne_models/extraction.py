"""
Extraction models.

Defines the schema for CSS/XPath-based extraction (Phase 1) and the
output format for extracted data. Phase 3 adds LLM-based extraction
but uses the same output models.

ExtractionSchema is what the user provides (or what auto-schema discovers):
    {
        "fields": {
            "title": {"selector": "h1", "type": "text"},
            "price": {"selector": ".price_color", "type": "text", "transform": "strip_currency"},
            "image": {"selector": "img.main", "attr": "src", "type": "attribute"}
        }
    }

ExtractionResult is what comes out after parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class FieldType(StrEnum):
    """What to extract from a matched element."""

    TEXT = "text"  # .text_content()
    HTML = "html"  # .tostring() (inner HTML)
    ATTRIBUTE = "attribute"  # element.get(attr)


class TransformType(StrEnum):
    """Built-in post-extraction transforms.

    Applied after extracting the raw value from the DOM to clean/normalize it.
    """

    STRIP_CURRENCY = "strip_currency"  # "$19.99" -> 19.99
    STRIP_WHITESPACE = "strip_whitespace"  # collapse and trim whitespace
    TO_ABSOLUTE_URL = "to_absolute_url"  # resolve relative URLs
    PARSE_DATE = "parse_date"  # parse common date formats to ISO


class FieldConfig(BaseModel):
    """Configuration for extracting a single field from the page.

    Supports both CSS selectors and XPath. If the selector is an XPath
    expression (starts with / or //), XPath is used automatically.
    """

    selector: str  # CSS selector or XPath expression
    type: FieldType = FieldType.TEXT
    attr: str | None = None  # Required when type == ATTRIBUTE
    transform: TransformType | None = None
    multiple: bool = False  # If True, extract all matches as a list


class ExtractionSchema(BaseModel):
    """Schema defining what to extract from a page.

    User-provided for known sites, or auto-discovered by the AI
    extraction engine in Phase 3.
    """

    fields: dict[str, FieldConfig]


class ExtractionResult(BaseModel):
    """Output of an extraction operation.

    Contains the extracted data plus metadata about the extraction
    (timing, schema used, source URL). Supports both CSS/XPath extraction
    (Phase 1) and AI-based extraction (Phase 3) with full provenance.
    """

    job_id: UUID
    source_url: str
    extracted_data: dict  # Field name -> extracted value(s)
    schema_hash: str | None = None  # Hash of the schema used
    elapsed_ms: int = 0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # --- AI Extraction Provenance (Phase 3) ---
    extraction_method: str = "css_xpath"  # "css_xpath" | "llm" | "vision" | "auto_schema"
    model_used: str | None = None  # LiteLLM model id (e.g., "gemini/gemini-2.5-flash")
    tokens_input: int | None = None  # Input tokens consumed
    tokens_output: int | None = None  # Output tokens generated
    estimated_cost_usd: float | None = None  # Estimated cost of the extraction
    retry_count: int = 0  # Number of retries needed
    confidence: float | None = None  # Extraction confidence (0.0 - 1.0)
    cascade_path: list[str] | None = None  # Models tried in cascade order
