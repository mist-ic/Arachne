"""
Tests for auto-schema discovery.
"""

from __future__ import annotations

import pytest

from arachne_extraction.schema_discovery import (
    DiscoveredSchema,
    FieldDefinition,
    _to_class_name,
    _hash_schema,
    find_repeated_subtrees,
    generate_pydantic_model,
)
from pydantic import BaseModel


# ============================================================================
# Test HTML Fixtures
# ============================================================================


LISTING_HTML = """
<html>
<body>
    <div class="results">
        <div class="product-card">
            <h3 class="title">Widget A</h3>
            <span class="price">$19.99</span>
            <p class="description">A great widget for beginners.</p>
        </div>
        <div class="product-card">
            <h3 class="title">Widget B</h3>
            <span class="price">$24.99</span>
            <p class="description">Professional grade widget.</p>
        </div>
        <div class="product-card">
            <h3 class="title">Widget C</h3>
            <span class="price">$34.99</span>
            <p class="description">Enterprise edition widget.</p>
        </div>
        <div class="product-card">
            <h3 class="title">Widget D</h3>
            <span class="price">$44.99</span>
            <p class="description">Premium quality widget.</p>
        </div>
    </div>
</body>
</html>
"""


SINGLE_ENTITY_HTML = """
<html>
<body>
    <article>
        <h1>Widget Pro - Detailed Review</h1>
        <p>This is a comprehensive review of the Widget Pro product.</p>
    </article>
</body>
</html>
"""


# ============================================================================
# Repeated Subtree Detection Tests
# ============================================================================


class TestFindRepeatedSubtrees:
    """Tests for DOM-based repeated subtree detection."""

    def test_finds_repeated_structures(self):
        clusters = find_repeated_subtrees(LISTING_HTML, min_repetitions=3)
        assert len(clusters) > 0

    def test_cluster_count_correct(self):
        clusters = find_repeated_subtrees(LISTING_HTML, min_repetitions=3)
        # Should find a cluster with 4 repetitions (product cards)
        high_count = [c for c in clusters if c.count >= 4]
        assert len(high_count) > 0

    def test_cluster_has_representative(self):
        clusters = find_repeated_subtrees(LISTING_HTML, min_repetitions=3)
        for cluster in clusters:
            assert len(cluster.representative_html) > 0
            assert len(cluster.representative_text) > 0

    def test_single_entity_no_clusters(self):
        clusters = find_repeated_subtrees(SINGLE_ENTITY_HTML, min_repetitions=3)
        # Single entity page shouldn't have many repeated structures
        # (may have some from HTML boilerplate, but not entity-level)
        assert len(clusters) == 0 or all(c.count < 3 for c in clusters)

    def test_min_repetitions_filter(self):
        clusters_low = find_repeated_subtrees(LISTING_HTML, min_repetitions=2)
        clusters_high = find_repeated_subtrees(LISTING_HTML, min_repetitions=5)
        assert len(clusters_low) >= len(clusters_high)


# ============================================================================
# Dynamic Pydantic Model Generation Tests
# ============================================================================


class TestGeneratePydanticModel:
    """Tests for dynamic model creation."""

    def test_generates_model(self):
        schema = DiscoveredSchema(
            entity_type="product",
            fields=[
                FieldDefinition(name="name", type="str", required=True),
                FieldDefinition(name="price", type="float", required=True),
                FieldDefinition(name="description", type="str", required=False),
            ],
        )
        model = generate_pydantic_model(schema)
        assert issubclass(model, BaseModel)

    def test_model_has_correct_fields(self):
        schema = DiscoveredSchema(
            entity_type="product",
            fields=[
                FieldDefinition(name="name", type="str", required=True),
                FieldDefinition(name="price", type="float", required=True),
            ],
        )
        model = generate_pydantic_model(schema)
        assert "name" in model.model_fields
        assert "price" in model.model_fields

    def test_model_validates_data(self):
        schema = DiscoveredSchema(
            entity_type="product",
            fields=[
                FieldDefinition(name="name", type="str", required=True),
                FieldDefinition(name="price", type="float", required=True),
            ],
        )
        model = generate_pydantic_model(schema)
        instance = model(name="Widget", price=29.99)
        assert instance.name == "Widget"
        assert instance.price == 29.99

    def test_optional_fields(self):
        schema = DiscoveredSchema(
            entity_type="product",
            fields=[
                FieldDefinition(name="name", type="str", required=True),
                FieldDefinition(name="notes", type="str", required=False),
            ],
        )
        model = generate_pydantic_model(schema)
        instance = model(name="Widget")  # notes is optional
        assert instance.name == "Widget"
        assert instance.notes is None

    def test_model_class_name(self):
        schema = DiscoveredSchema(
            entity_type="job_listing",
            fields=[FieldDefinition(name="title", type="str")],
        )
        model = generate_pydantic_model(schema)
        assert model.__name__ == "JobListing"

    def test_supported_types(self):
        schema = DiscoveredSchema(
            entity_type="test",
            fields=[
                FieldDefinition(name="text_field", type="str"),
                FieldDefinition(name="int_field", type="int"),
                FieldDefinition(name="float_field", type="float"),
                FieldDefinition(name="bool_field", type="bool"),
            ],
        )
        model = generate_pydantic_model(schema)
        instance = model(text_field="hello", int_field=42, float_field=3.14, bool_field=True)
        assert instance.int_field == 42


# ============================================================================
# Utility Tests
# ============================================================================


class TestUtilities:
    """Tests for utility functions."""

    def test_to_class_name(self):
        assert _to_class_name("product") == "Product"
        assert _to_class_name("job_listing") == "JobListing"
        assert _to_class_name("real_estate_listing") == "RealEstateListing"

    def test_hash_schema(self):
        schema = DiscoveredSchema(
            entity_type="product",
            fields=[
                FieldDefinition(name="name", type="str"),
                FieldDefinition(name="price", type="float"),
            ],
        )
        hash1 = _hash_schema(schema)
        assert len(hash1) == 16  # 16 char hex

    def test_hash_deterministic(self):
        schema = DiscoveredSchema(
            entity_type="product",
            fields=[FieldDefinition(name="name", type="str")],
        )
        assert _hash_schema(schema) == _hash_schema(schema)

    def test_different_schemas_different_hashes(self):
        schema1 = DiscoveredSchema(
            entity_type="product",
            fields=[FieldDefinition(name="name", type="str")],
        )
        schema2 = DiscoveredSchema(
            entity_type="article",
            fields=[FieldDefinition(name="title", type="str")],
        )
        assert _hash_schema(schema1) != _hash_schema(schema2)
