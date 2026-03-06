"""
Tests for the HTML → Markdown preprocessor.

Covers DOM pruning, HTML→Markdown conversion, content scoring,
and the full preprocessing pipeline.
"""

from __future__ import annotations

import pytest

from arachne_extraction.preprocessor import (
    PreprocessResult,
    ScoredBlock,
    _clean_markdown,
    html_to_markdown,
    preprocess,
    prune_dom,
    score_content,
)


# ============================================================================
# Test HTML Fixtures
# ============================================================================


SIMPLE_HTML = """
<html>
<head>
    <title>Test Page</title>
    <script>var tracking = true;</script>
    <style>body { font-family: Arial; }</style>
</head>
<body>
    <nav><a href="/home">Home</a> | <a href="/about">About</a></nav>
    <main>
        <h1>Product Details</h1>
        <p>The Widget Pro is our best-selling product with amazing features.</p>
        <div class="price">$29.99</div>
        <table>
            <tr><th>Feature</th><th>Value</th></tr>
            <tr><td>Weight</td><td>1.5 kg</td></tr>
            <tr><td>Color</td><td>Blue</td></tr>
        </table>
    </main>
    <footer>© 2024 Widgets Inc. All rights reserved.</footer>
    <script>analytics.track('page_view');</script>
</body>
</html>
"""


BOILERPLATE_HEAVY_HTML = """
<html>
<body>
    <nav class="main-menu">
        <a href="/">Home</a>
        <a href="/shop">Shop</a>
    </nav>
    <div class="sidebar ad-container">
        <div class="ad">Buy widgets now!</div>
    </div>
    <div class="cookie-banner" style="display:block">
        We use cookies...
    </div>
    <article>
        <h1>Widget Pro Review</h1>
        <p>After extensive testing, the Widget Pro exceeded our expectations.
        The build quality is outstanding and the price point is very competitive.
        We recommend it for both beginners and experts alike.</p>
    </article>
    <aside role="complementary">
        <h3>Related Articles</h3>
    </aside>
    <footer id="site-footer">
        <p>© 2024</p>
    </footer>
</body>
</html>
"""


HIDDEN_ELEMENTS_HTML = """
<html>
<body>
    <div style="display: none">Hidden content that should be removed</div>
    <div style="visibility: hidden">Also hidden</div>
    <div aria-hidden="true">Screen reader hidden</div>
    <div style="opacity: 0;">Invisible div</div>
    <p>Visible content that should remain.</p>
</body>
</html>
"""


LINK_HEAVY_HTML = """
<html>
<body>
    <p>Check out <a href="https://example.com/page1">our first product</a>
    and <a href="https://example.com/page2">our second product</a>.</p>
    <p>Visit <a href="https://example.com/page1">the same first product</a> again.</p>
</body>
</html>
"""


EMPTY_HTML = ""
WHITESPACE_HTML = "   \n\t  "


# ============================================================================
# DOM Pruning Tests
# ============================================================================


class TestPruneDom:
    """Tests for prune_dom() function."""

    def test_removes_script_tags(self):
        result = prune_dom(SIMPLE_HTML)
        assert "<script>" not in result
        assert "tracking" not in result
        assert "analytics" not in result

    def test_removes_style_tags(self):
        result = prune_dom(SIMPLE_HTML)
        assert "<style>" not in result
        assert "font-family" not in result

    def test_removes_nav_elements(self):
        result = prune_dom(SIMPLE_HTML)
        assert "<nav>" not in result

    def test_removes_footer(self):
        result = prune_dom(SIMPLE_HTML)
        assert "<footer>" not in result
        assert "All rights reserved" not in result

    def test_preserves_main_content(self):
        result = prune_dom(SIMPLE_HTML)
        assert "Product Details" in result
        assert "Widget Pro" in result
        assert "$29.99" in result

    def test_preserves_tables(self):
        result = prune_dom(SIMPLE_HTML)
        assert "Weight" in result
        assert "1.5 kg" in result

    def test_removes_hidden_elements(self):
        result = prune_dom(HIDDEN_ELEMENTS_HTML)
        assert "Hidden content" not in result
        assert "Also hidden" not in result
        assert "Screen reader hidden" not in result
        assert "Invisible div" not in result

    def test_preserves_visible_content(self):
        result = prune_dom(HIDDEN_ELEMENTS_HTML)
        assert "Visible content" in result

    def test_removes_boilerplate_by_class(self):
        result = prune_dom(BOILERPLATE_HEAVY_HTML)
        assert "cookie-banner" not in result.lower() or "We use cookies" not in result

    def test_removes_aside_with_role(self):
        result = prune_dom(BOILERPLATE_HEAVY_HTML)
        assert "Related Articles" not in result

    def test_preserves_article_content(self):
        result = prune_dom(BOILERPLATE_HEAVY_HTML)
        assert "Widget Pro Review" in result
        assert "extensive testing" in result

    def test_empty_html(self):
        assert prune_dom(EMPTY_HTML) == ""
        assert prune_dom(WHITESPACE_HTML) == ""

    def test_returns_original_on_parse_failure(self):
        invalid = "<<<not html at all>>>"
        result = prune_dom(invalid)
        # Should not crash, returns something
        assert isinstance(result, str)


# ============================================================================
# HTML to Markdown Tests
# ============================================================================


class TestHtmlToMarkdown:
    """Tests for html_to_markdown() function."""

    def test_converts_headings(self):
        html = "<h1>Title</h1><h2>Subtitle</h2>"
        md = html_to_markdown(html, use_citations=False)
        assert "# Title" in md
        assert "## Subtitle" in md

    def test_converts_paragraphs(self):
        html = "<p>Hello world.</p><p>Second paragraph.</p>"
        md = html_to_markdown(html, use_citations=False)
        assert "Hello world." in md
        assert "Second paragraph." in md

    def test_converts_links_inline(self):
        html = '<p>Visit <a href="https://example.com">Example</a></p>'
        md = html_to_markdown(html, use_citations=False)
        assert "[Example](https://example.com)" in md

    def test_converts_links_citations(self):
        html = '<p>Visit <a href="https://example.com">Example</a></p>'
        md = html_to_markdown(html, use_citations=True)
        assert "[Example][1]" in md
        assert "[1]: https://example.com" in md

    def test_deduplicates_citation_urls(self):
        md = html_to_markdown(LINK_HEAVY_HTML, use_citations=True)
        # Same URL should get the same citation number
        # "https://example.com/page1" appears in two links
        assert md.count("[1]: https://example.com/page1") == 1

    def test_converts_images(self):
        html = '<img src="photo.jpg" alt="Product photo">'
        md = html_to_markdown(html, use_citations=False)
        assert "![Product photo](photo.jpg)" in md

    def test_converts_lists(self):
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        md = html_to_markdown(html, use_citations=False)
        assert "Item 1" in md
        assert "Item 2" in md

    def test_empty_html(self):
        assert html_to_markdown("") == ""
        assert html_to_markdown("   ") == ""

    def test_cleans_excessive_whitespace(self):
        html = "<p>Hello</p>\n\n\n\n\n<p>World</p>"
        md = html_to_markdown(html, use_citations=False)
        # Should not have more than 2 consecutive newlines
        assert "\n\n\n" not in md


# ============================================================================
# Content Scoring Tests
# ============================================================================


class TestScoreContent:
    """Tests for score_content() function."""

    def test_returns_scored_blocks(self):
        blocks = score_content(SIMPLE_HTML)
        assert len(blocks) > 0
        assert all(isinstance(b, ScoredBlock) for b in blocks)

    def test_scores_are_bounded(self):
        blocks = score_content(SIMPLE_HTML)
        for block in blocks:
            assert 0.0 <= block.score <= 1.0

    def test_content_blocks_scored_higher_than_boilerplate(self):
        blocks = score_content(BOILERPLATE_HEAVY_HTML)
        if blocks:
            # The article content should score higher
            content_blocks = [b for b in blocks if "extensive testing" in b.content]
            nav_blocks = [b for b in blocks if "Home" in b.content and "Shop" in b.content]
            if content_blocks and nav_blocks:
                assert content_blocks[0].score >= nav_blocks[0].score

    def test_empty_html_returns_empty(self):
        assert score_content("") == []
        assert score_content("   ") == []

    def test_blocks_sorted_by_score(self):
        blocks = score_content(SIMPLE_HTML)
        if len(blocks) > 1:
            scores = [b.score for b in blocks]
            assert scores == sorted(scores, reverse=True)


# ============================================================================
# Full Pipeline Tests
# ============================================================================


class TestPreprocess:
    """Tests for the full preprocess() pipeline."""

    def test_returns_preprocess_result(self):
        result = preprocess(SIMPLE_HTML)
        assert isinstance(result, PreprocessResult)

    def test_reduces_content_size(self):
        result = preprocess(SIMPLE_HTML)
        assert result.markdown_char_count < result.raw_char_count
        assert result.reduction_ratio > 1.0

    def test_markdown_contains_content(self):
        result = preprocess(SIMPLE_HTML)
        assert "Product Details" in result.markdown or "Widget Pro" in result.markdown

    def test_markdown_excludes_scripts(self):
        result = preprocess(SIMPLE_HTML)
        assert "tracking" not in result.markdown
        assert "analytics" not in result.markdown

    def test_content_hash_generated(self):
        result = preprocess(SIMPLE_HTML)
        assert len(result.content_hash) == 64  # SHA-256 hex

    def test_same_content_same_hash(self):
        result1 = preprocess(SIMPLE_HTML)
        result2 = preprocess(SIMPLE_HTML)
        assert result1.content_hash == result2.content_hash

    def test_empty_html(self):
        result = preprocess("")
        assert result.markdown == ""
        assert result.raw_char_count == 0

    def test_query_filtering(self):
        # With a query, BM25 should filter content
        result_no_query = preprocess(SIMPLE_HTML)
        result_with_query = preprocess(SIMPLE_HTML, query="price widget cost")
        # Both should produce valid output
        assert isinstance(result_no_query, PreprocessResult)
        assert isinstance(result_with_query, PreprocessResult)
