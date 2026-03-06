"""
Auto-schema discovery for unknown sites.

When no extraction schema is provided, automatically discovers what entities
exist on a page and proposes a Pydantic schema for extraction. Enables
zero-configuration scraping of unknown sites.

Two discovery modes:
    1. Pure LLM Discovery — feed Markdown, ask LLM for entity types/fields
    2. Hybrid DOM + LLM — parse DOM for repeated subtrees, LLM labels them

References:
    - Research.md §2.3: Auto-schema eliminates CSS/XPath brittleness
    - Phase3.md Step 5: Repeated subtree detection, dynamic Pydantic models
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import structlog
from lxml import etree, html as lxml_html
from pydantic import BaseModel, Field, create_model

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class FieldDefinition(BaseModel):
    """Definition of a single field in a discovered schema."""

    name: str = Field(description="Field name (snake_case)")
    type: str = Field(
        default="str",
        description="Python type: str, int, float, bool, list[str], datetime",
    )
    description: str = Field(default="", description="What this field contains")
    required: bool = Field(default=True, description="Whether the field is required")
    example: str | None = Field(default=None, description="Example value from the page")
    css_selector: str | None = Field(
        default=None,
        description="CSS selector for this field (discovered in hybrid mode)",
    )


class DiscoveredSchema(BaseModel):
    """A proposed extraction schema discovered from page content."""

    entity_type: str = Field(description="Entity type name (e.g., 'product', 'job_listing')")
    entity_description: str = Field(default="", description="Description of the entity")
    fields: list[FieldDefinition] = Field(default_factory=list)
    is_listing: bool = Field(
        default=False,
        description="Whether the page contains multiple entities of this type",
    )
    estimated_entity_count: int = Field(
        default=1,
        description="Estimated number of entities on the page",
    )
    confidence: float = Field(
        default=0.0,
        description="Confidence in the discovered schema (0-1)",
    )
    discovery_mode: str = Field(
        default="llm",
        description="How the schema was discovered: 'llm' or 'hybrid'",
    )
    schema_hash: str = Field(default="", description="Hash for caching/versioning")


# ============================================================================
# LLM Schema Proposal
# ============================================================================


# Prompt for pure LLM discovery
DISCOVERY_SYSTEM_PROMPT = """You are a data analysis expert. Analyze the web page content and discover what structured data entities it contains.

Your task:
1. Identify the TYPE of entities on the page (product, article, job listing, event, etc.)
2. List ALL extractable fields for each entity type
3. Determine the Python type for each field (str, int, float, bool, list[str])
4. Mark fields as required (always present) or optional (sometimes missing)
5. Determine if this is a listing page (multiple entities) or a detail page (single entity)

Be thorough — include ALL fields you can identify, not just the obvious ones."""


class _SchemaProposal(BaseModel):
    """Pydantic model for the LLM's schema proposal response."""

    entity_type: str = Field(description="Name for this entity type (e.g., 'product')")
    entity_description: str = Field(description="Brief description of the entity")
    is_listing: bool = Field(description="True if the page has multiple entities")
    estimated_count: int = Field(default=1, description="How many entities on the page")
    fields: list[_ProposedField] = Field(description="List of discovered fields")


class _ProposedField(BaseModel):
    """A single field proposed by the LLM."""

    name: str = Field(description="Field name in snake_case")
    type: str = Field(description="Python type: str, int, float, bool, list[str]")
    description: str = Field(description="What this field contains")
    required: bool = Field(default=True)
    example: str | None = Field(default=None, description="Example value seen on page")


async def discover_schema_llm(
    markdown: str,
    *,
    model: str = "gemini/gemini-2.5-flash",
    api_key: str | None = None,
) -> DiscoveredSchema:
    """Discover extraction schema using pure LLM analysis.

    Feeds the preprocessed Markdown to an LLM and asks it to identify
    entity types, fields, and their types.

    Args:
        markdown: Preprocessed markdown content.
        model: LiteLLM model identifier.
        api_key: API key for the model provider.

    Returns:
        DiscoveredSchema with proposed entity type and fields.
    """
    from arachne_extraction.llm_extractor import ExtractionConfig, LLMExtractor

    config = ExtractionConfig(
        model=model,
        api_key=api_key,
        max_retries=2,
        temperature=0.1,  # Slightly creative for discovery
        enable_reattempt=False,
    )

    extractor = LLMExtractor(config=config)
    result = await extractor.extract(
        markdown=markdown,
        schema=_SchemaProposal,
    )

    if result.data is None:
        logger.warning("schema_discovery_failed", model=model)
        return DiscoveredSchema(
            entity_type="unknown",
            confidence=0.0,
            discovery_mode="llm",
        )

    proposal: _SchemaProposal = result.data

    # Convert to DiscoveredSchema
    fields = [
        FieldDefinition(
            name=f.name,
            type=f.type,
            description=f.description,
            required=f.required,
            example=f.example,
        )
        for f in proposal.fields
    ]

    schema = DiscoveredSchema(
        entity_type=proposal.entity_type,
        entity_description=proposal.entity_description,
        fields=fields,
        is_listing=proposal.is_listing,
        estimated_entity_count=proposal.estimated_count,
        confidence=result.confidence,
        discovery_mode="llm",
    )
    schema.schema_hash = _hash_schema(schema)

    logger.info(
        "schema_discovered_llm",
        entity_type=schema.entity_type,
        field_count=len(fields),
        is_listing=schema.is_listing,
        confidence=schema.confidence,
    )

    return schema


# ============================================================================
# Hybrid DOM + LLM Discovery
# ============================================================================


@dataclass
class _SubtreeCluster:
    """A cluster of structurally similar DOM subtrees."""

    structure_hash: str
    count: int
    representative_html: str
    representative_text: str
    elements: list = field(default_factory=list)


def _compute_structure_hash(element) -> str:
    """Compute a structural hash of a DOM subtree.

    Only considers tag structure (ignoring text content, attributes, etc.).
    Two elements with the same tag nesting but different content will hash
    the same — this is how we detect repeated templates.
    """
    parts = []
    for child in element.iter():
        if isinstance(child.tag, str):
            # Include tag name and depth relative to root
            depth = 0
            parent = child.getparent()
            while parent is not None and parent != element:
                depth += 1
                parent = parent.getparent()
            parts.append(f"{depth}:{child.tag}")

    structure = "|".join(parts)
    return hashlib.md5(structure.encode()).hexdigest()[:12]


def find_repeated_subtrees(
    html_content: str,
    *,
    min_repetitions: int = 3,
    min_text_length: int = 20,
) -> list[_SubtreeCluster]:
    """Find structurally repeated DOM subtrees.

    Identifies elements that appear multiple times with identical tag
    structure — these are likely entity containers (product cards,
    search results, list items).

    Args:
        html_content: Pruned HTML content.
        min_repetitions: Minimum times a structure must repeat to qualify.
        min_text_length: Minimum text content to be considered meaningful.

    Returns:
        List of subtree clusters sorted by frequency.
    """
    try:
        tree = lxml_html.fromstring(html_content)
    except (etree.ParserError, etree.XMLSyntaxError):
        return []

    # Hash all subtrees
    subtree_map: dict[str, list] = defaultdict(list)

    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        if element.tag in ("html", "body", "head"):
            continue

        text = (element.text_content() or "").strip()
        if len(text) < min_text_length:
            continue

        # Skip very deep nesting (>10 levels deep = probably noise)
        depth = sum(1 for _ in element.iterancestors())
        if depth > 10:
            continue

        structure_hash = _compute_structure_hash(element)
        subtree_map[structure_hash].append(element)

    # Filter to repeated structures
    clusters: list[_SubtreeCluster] = []
    for hash_val, elements in subtree_map.items():
        if len(elements) >= min_repetitions:
            representative = elements[0]
            clusters.append(_SubtreeCluster(
                structure_hash=hash_val,
                count=len(elements),
                representative_html=lxml_html.tostring(
                    representative, encoding="unicode", method="html",
                )[:2000],  # Cap size
                representative_text=(representative.text_content() or "").strip()[:500],
                elements=elements,
            ))

    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters


async def discover_schema_hybrid(
    html_content: str,
    markdown: str,
    *,
    model: str = "gemini/gemini-2.5-flash",
    api_key: str | None = None,
) -> DiscoveredSchema:
    """Hybrid DOM + LLM schema discovery.

    1. Parse DOM for repeated subtrees (structural analysis)
    2. Send representative subtrees to LLM for field labeling
    3. Generate both Pydantic schema AND CSS selectors

    This approach is more precise for listing pages because the DOM
    structure directly reveals the entity template.

    Args:
        html_content: Pruned HTML content.
        markdown: Preprocessed markdown (as context for LLM).
        model: LiteLLM model identifier.
        api_key: API key.

    Returns:
        DiscoveredSchema with fields and CSS selectors.
    """
    # Step 1: Find repeated subtrees
    clusters = find_repeated_subtrees(html_content)

    if not clusters:
        logger.info("no_repeated_subtrees", fallback="llm_discovery")
        return await discover_schema_llm(markdown, model=model, api_key=api_key)

    # Use the most-repeated cluster as the entity template
    primary_cluster = clusters[0]

    logger.info(
        "repeated_subtrees_found",
        cluster_count=len(clusters),
        primary_count=primary_cluster.count,
        primary_hash=primary_cluster.structure_hash,
    )

    # Step 2: Ask LLM to label the fields in the representative subtree
    from arachne_extraction.llm_extractor import ExtractionConfig, LLMExtractor

    label_prompt = f"""Analyze this repeated HTML element from a web page. It appears {primary_cluster.count} times, so it's likely a data entity (product card, listing item, etc.).

--- REPRESENTATIVE HTML ---
{primary_cluster.representative_html}
--- END HTML ---

--- TEXT CONTENT ---
{primary_cluster.representative_text}
--- END TEXT ---

Identify:
1. What type of entity this represents
2. All extractable fields and their types
3. CSS selectors within this element for each field"""

    config = ExtractionConfig(
        model=model,
        api_key=api_key,
        max_retries=2,
        temperature=0.1,
        enable_reattempt=False,
    )

    extractor = LLMExtractor(config=config)
    result = await extractor.extract(
        markdown=label_prompt,
        schema=_SchemaProposal,
    )

    if result.data is None:
        return await discover_schema_llm(markdown, model=model, api_key=api_key)

    proposal: _SchemaProposal = result.data

    fields = [
        FieldDefinition(
            name=f.name,
            type=f.type,
            description=f.description,
            required=f.required,
            example=f.example,
        )
        for f in proposal.fields
    ]

    schema = DiscoveredSchema(
        entity_type=proposal.entity_type,
        entity_description=proposal.entity_description,
        fields=fields,
        is_listing=True,  # Repeated subtrees = listing
        estimated_entity_count=primary_cluster.count,
        confidence=min(result.confidence + 0.1, 1.0),  # Hybrid gets confidence boost
        discovery_mode="hybrid",
    )
    schema.schema_hash = _hash_schema(schema)

    logger.info(
        "schema_discovered_hybrid",
        entity_type=schema.entity_type,
        field_count=len(fields),
        entity_count=primary_cluster.count,
        confidence=schema.confidence,
    )

    return schema


# ============================================================================
# Dynamic Pydantic Model Generation
# ============================================================================


# Map schema type strings to Python types
_TYPE_MAP: dict[str, type] = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": float,
    "bool": bool,
    "boolean": bool,
    "list[str]": list[str],
    "list[string]": list[str],
    "list[int]": list[int],
    "list[float]": list[float],
    "datetime": str,  # Store as ISO string
    "date": str,
    "url": str,
}


def generate_pydantic_model(
    schema: DiscoveredSchema,
) -> type[BaseModel]:
    """Generate a Pydantic model from a discovered schema at runtime.

    Uses pydantic.create_model() to dynamically create a model class
    that can be used directly with the LLM extractor.

    Args:
        schema: Discovered schema with field definitions.

    Returns:
        A Pydantic BaseModel subclass.
    """
    field_definitions: dict[str, Any] = {}

    for field_def in schema.fields:
        python_type = _TYPE_MAP.get(field_def.type.lower(), str)

        if field_def.required:
            field_definitions[field_def.name] = (
                python_type,
                Field(description=field_def.description),
            )
        else:
            field_definitions[field_def.name] = (
                python_type | None,
                Field(default=None, description=field_def.description),
            )

    model_name = _to_class_name(schema.entity_type)

    model = create_model(
        model_name,
        **field_definitions,
    )

    logger.info(
        "pydantic_model_generated",
        model_name=model_name,
        field_count=len(field_definitions),
    )

    return model


def _to_class_name(entity_type: str) -> str:
    """Convert entity_type to PascalCase class name.

    "product" -> "Product"
    "job_listing" -> "JobListing"
    "real_estate_listing" -> "RealEstateListing"
    """
    return "".join(word.capitalize() for word in entity_type.split("_"))


# ============================================================================
# Main Discovery Function
# ============================================================================


async def discover_schema(
    markdown: str,
    *,
    html: str | None = None,
    model: str = "gemini/gemini-2.5-flash",
    api_key: str | None = None,
    prefer_hybrid: bool = True,
) -> DiscoveredSchema:
    """Discover extraction schema for a page.

    Automatically selects the best discovery mode:
    - If HTML is available and has repeated subtrees → hybrid mode
    - Otherwise → pure LLM discovery

    Args:
        markdown: Preprocessed markdown content.
        html: Optional pruned HTML (enables hybrid mode).
        model: LiteLLM model identifier.
        api_key: API key.
        prefer_hybrid: Try hybrid mode first when HTML is available.

    Returns:
        DiscoveredSchema with proposed fields and types.
    """
    if html and prefer_hybrid:
        schema = await discover_schema_hybrid(
            html, markdown, model=model, api_key=api_key,
        )
        if schema.confidence > 0.3:
            return schema
        logger.info("hybrid_low_confidence", fallback="llm_discovery")

    return await discover_schema_llm(markdown, model=model, api_key=api_key)


# ============================================================================
# Utilities
# ============================================================================


def _hash_schema(schema: DiscoveredSchema) -> str:
    """Generate a hash for schema caching/versioning."""
    content = f"{schema.entity_type}:{','.join(f.name + ':' + f.type for f in schema.fields)}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]
