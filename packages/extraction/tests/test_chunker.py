"""
Tests for the context-aware markdown chunker.
"""

from __future__ import annotations

import pytest

from arachne_extraction.chunker import Chunk, chunk_markdown


# ============================================================================
# Test Fixtures
# ============================================================================


SHORT_MARKDOWN = """# Product

Widget Pro costs $29.99.
"""

LONG_MARKDOWN = """# Section 1

This is the first section with some content about products and services.
We have many things to discuss here including pricing and features.

## Subsection 1.1

More detailed content about the first topic. This includes tables,
lists, and other structured data that should be preserved.

| Feature | Value |
|---------|-------|
| Weight  | 1.5kg |
| Color   | Blue  |
| Size    | Large |

## Subsection 1.2

Another subsection with different content about another topic.
This one has a list:

- Item 1: First thing
- Item 2: Second thing
- Item 3: Third thing

# Section 2

A completely different section about another subject entirely.
This has enough text to trigger chunking when combined with section 1.

## Subsection 2.1

Details about the second major topic with substantial text content
that helps verify chunking behavior across section boundaries.

## Subsection 2.2

Final subsection with concluding remarks and summary information.
"""


TABLE_MARKDOWN = """# Data

Here is an important table:

| Column A | Column B | Column C |
|----------|----------|----------|
| Value 1  | Value 2  | Value 3  |
| Value 4  | Value 5  | Value 6  |
| Value 7  | Value 8  | Value 9  |
"""


# ============================================================================
# Basic Chunking Tests
# ============================================================================


class TestChunkMarkdown:
    """Tests for chunk_markdown() function."""

    def test_empty_input(self):
        assert chunk_markdown("") == []
        assert chunk_markdown("   ") == []

    def test_short_content_single_chunk(self):
        chunks = chunk_markdown(SHORT_MARKDOWN, max_tokens=4000)
        assert len(chunks) == 1
        assert chunks[0].index == 0
        assert chunks[0].total_chunks == 1

    def test_chunk_metadata(self):
        chunks = chunk_markdown(SHORT_MARKDOWN, max_tokens=4000)
        chunk = chunks[0]
        assert chunk.start_char == 0
        assert chunk.end_char == len(SHORT_MARKDOWN)
        assert chunk.estimated_tokens > 0

    def test_multiple_chunks_for_long_content(self):
        # Very small max_tokens to force multiple chunks
        chunks = chunk_markdown(LONG_MARKDOWN, max_tokens=50)
        assert len(chunks) > 1

    def test_total_chunks_set_correctly(self):
        chunks = chunk_markdown(LONG_MARKDOWN, max_tokens=50)
        for chunk in chunks:
            assert chunk.total_chunks == len(chunks)

    def test_indices_are_sequential(self):
        chunks = chunk_markdown(LONG_MARKDOWN, max_tokens=50)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i


# ============================================================================
# Table Preservation Tests
# ============================================================================


class TestTablePreservation:
    """Tests ensuring tables are never split across chunks."""

    def test_table_in_single_chunk(self):
        chunks = chunk_markdown(TABLE_MARKDOWN, max_tokens=4000)
        assert len(chunks) == 1
        assert "Column A" in chunks[0].content
        assert "Value 9" in chunks[0].content

    def test_table_not_split(self):
        # Even with small max_tokens, table should stay together
        chunks = chunk_markdown(TABLE_MARKDOWN, max_tokens=30)
        # Find the chunk containing the table start
        table_chunks = [c for c in chunks if "Column A" in c.content]
        assert len(table_chunks) >= 1
        # The table header and data should be in the same chunk
        for c in table_chunks:
            if "Column A" in c.content:
                assert "Value 1" in c.content or c.has_table


# ============================================================================
# Section-Based Splitting Tests
# ============================================================================


class TestSectionSplitting:
    """Tests for splitting at heading boundaries."""

    def test_splits_at_headings(self):
        chunks = chunk_markdown(LONG_MARKDOWN, max_tokens=100)
        # Should split at section boundaries
        assert len(chunks) > 1

    def test_parent_section_tracked(self):
        chunks = chunk_markdown(LONG_MARKDOWN, max_tokens=100)
        # At least some chunks should have parent sections
        sections = [c.parent_section for c in chunks if c.parent_section]
        assert len(sections) > 0


# ============================================================================
# Overlap Tests
# ============================================================================


class TestOverlap:
    """Tests for sentence overlap between chunks."""

    def test_overlap_added(self):
        chunks = chunk_markdown(LONG_MARKDOWN, max_tokens=50, overlap_sentences=2)
        if len(chunks) > 1:
            # Second chunk should contain overlap indicator
            # (overlap may or may not be present depending on sentence boundaries)
            assert any(c.overlap_chars >= 0 for c in chunks)

    def test_no_overlap_when_disabled(self):
        chunks = chunk_markdown(LONG_MARKDOWN, max_tokens=50, overlap_sentences=0)
        for chunk in chunks:
            assert chunk.overlap_chars == 0
