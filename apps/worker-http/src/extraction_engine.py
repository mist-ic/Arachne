"""
CSS/XPath extraction engine — Phase 1.

Extracts structured data from raw HTML using CSS selectors and XPath
expressions as defined by an ExtractionSchema from core-models.

This is deterministic, rule-based extraction. Phase 3 adds LLM-based
extraction but using the same ExtractionResult output format.

Uses lxml for parsing (fastest Python HTML parser) with cssselect
for CSS selector support.

Usage:
    from extraction_engine import extract

    result = extract(
        html="<html>...",
        url="https://example.com",
        job_id="uuid-string",
        schema=ExtractionSchema(fields={
            "title": FieldConfig(selector="h1", type="text"),
            "price": FieldConfig(selector=".price", type="text", transform="strip_currency"),
        })
    )
"""

from __future__ import annotations

import hashlib
import json
import re
from time import perf_counter
from urllib.parse import urljoin

from lxml import html as lxml_html

from arachne_models.extraction import (
    ExtractionResult,
    ExtractionSchema,
    FieldConfig,
    FieldType,
    TransformType,
)


def extract(
    html_content: str,
    url: str,
    job_id: str,
    schema: ExtractionSchema,
) -> ExtractionResult:
    """Extract structured data from HTML using a schema.

    Parses HTML with lxml, then applies each field's selector
    (CSS or XPath) to extract values. Transforms are applied
    post-extraction to clean/normalize the data.

    Args:
        html_content: Raw HTML string.
        url: Source URL (used for resolving relative URLs).
        job_id: UUID string for the result.
        schema: Extraction schema defining what to extract.

    Returns:
        ExtractionResult with extracted data and metadata.
    """
    start = perf_counter()

    # Parse HTML into a tree
    tree = lxml_html.fromstring(html_content)

    # Extract each field
    extracted = {}
    for field_name, field_config in schema.fields.items():
        value = _extract_field(tree, field_config, base_url=url)
        extracted[field_name] = value

    elapsed_ms = int((perf_counter() - start) * 1000)

    # Hash the schema for versioning (detect schema changes)
    schema_json = json.dumps(schema.model_dump(), sort_keys=True)
    schema_hash = hashlib.sha256(schema_json.encode()).hexdigest()[:16]

    return ExtractionResult(
        job_id=job_id,
        source_url=url,
        extracted_data=extracted,
        schema_hash=schema_hash,
        elapsed_ms=elapsed_ms,
    )


def _extract_field(
    tree,
    config: FieldConfig,
    base_url: str,
) -> str | list[str] | None:
    """Extract a single field from the parsed HTML tree.

    Auto-detects CSS vs XPath:
    - Selectors starting with / or // are treated as XPath
    - Everything else is treated as a CSS selector

    Args:
        tree: lxml parsed HTML tree.
        config: Field configuration (selector, type, transform, multiple).
        base_url: Base URL for resolving relative URLs.

    Returns:
        Extracted value(s) or None if not found.
    """
    selector = config.selector

    # Auto-detect CSS vs XPath
    if selector.startswith("/") or selector.startswith("("):
        # XPath expression
        elements = tree.xpath(selector)
    else:
        # CSS selector (converted to XPath by lxml)
        elements = tree.cssselect(selector)

    if not elements:
        return [] if config.multiple else None

    if config.multiple:
        values = [_extract_value(el, config) for el in elements]
        return [_apply_transform(v, config.transform, base_url) for v in values if v]
    else:
        value = _extract_value(elements[0], config)
        if value is None:
            return None
        return _apply_transform(value, config.transform, base_url)


def _extract_value(element, config: FieldConfig) -> str | None:
    """Extract the raw value from a single element based on FieldType."""
    match config.type:
        case FieldType.TEXT:
            text = element.text_content()
            return text.strip() if text else None
        case FieldType.HTML:
            return lxml_html.tostring(element, encoding="unicode")
        case FieldType.ATTRIBUTE:
            if config.attr is None:
                return None
            return element.get(config.attr)
    return None


def _apply_transform(
    value: str,
    transform: TransformType | None,
    base_url: str,
) -> str:
    """Apply a post-extraction transform to clean/normalize the value."""
    if transform is None:
        return value

    match transform:
        case TransformType.STRIP_CURRENCY:
            # "$19.99" -> "19.99", "£12.50" -> "12.50"
            cleaned = re.sub(r"[^\d.,]", "", value)
            return cleaned

        case TransformType.STRIP_WHITESPACE:
            # Collapse multiple whitespace and trim
            return re.sub(r"\s+", " ", value).strip()

        case TransformType.TO_ABSOLUTE_URL:
            # Resolve relative URLs against the page URL
            return urljoin(base_url, value)

        case TransformType.PARSE_DATE:
            # Return as-is for Phase 1 (Phase 3 adds dateutil parsing)
            return value.strip()

    return value
