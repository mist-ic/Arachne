"""
HTML → Markdown preprocessing pipeline.

The single biggest cost and accuracy optimization in the extraction stack.
Raw HTML is 50-100K tokens; after pruning + conversion, content-bearing
portions are 2-10K tokens — a 5-10x reduction that directly cuts LLM costs.

Pipeline:
    raw HTML → prune_dom → html_to_markdown → score_content → preprocess result

Design decisions:
    - lxml for parsing (fastest Python HTML parser)
    - markdownify for conversion (extensible, handles tables/images)
    - Link-to-citation conversion reduces inline noise
    - BM25 filtering for query-relevant extraction (optional)
    - Trafilatura integration for metadata extraction path

References:
    - Research.md §2.1: Token reduction via HTML→Markdown
    - Research.md §2.5: HTMLRAG minimal DOM subtree
    - RepoStudy §1: Crawl4AI link-to-citation pattern
    - RepoStudy §12: Trafilatura bare_extraction()
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from html import unescape
from typing import TYPE_CHECKING

import structlog
from lxml import etree, html as lxml_html
from markdownify import MarkdownConverter

if TYPE_CHECKING:
    from lxml.html import HtmlElement

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class ScoredBlock:
    """A block of content with a relevance score.

    Higher scores indicate more likely main content vs boilerplate.
    """

    content: str
    score: float  # 0.0 - 1.0
    tag: str  # Source HTML tag (e.g., 'p', 'div', 'article')
    position: int  # Order in the document
    char_count: int = 0
    link_density: float = 0.0  # Ratio of link text to total text


@dataclass
class PreprocessResult:
    """Output of the full preprocessing pipeline."""

    markdown: str  # Clean markdown output
    raw_char_count: int  # Original HTML character count
    pruned_char_count: int  # After DOM pruning
    markdown_char_count: int  # Final markdown character count
    reduction_ratio: float  # raw_char_count / markdown_char_count
    metadata: dict = field(default_factory=dict)  # Extracted metadata (title, author, etc.)
    content_hash: str = ""  # SHA-256 of the markdown content


# ============================================================================
# DOM Pruning Configuration
# ============================================================================


# Tags that carry zero extraction value — always removed
STRIP_TAGS: set[str] = {
    "script", "style", "noscript", "link", "meta",
    "iframe", "object", "embed", "applet",
    "svg", "canvas", "video", "audio", "source", "track",
    "template", "slot",
}

# Tags that usually contain boilerplate, not content
BOILERPLATE_TAGS: set[str] = {
    "nav", "header", "footer", "aside",
}

# ARIA roles indicating non-content regions
BOILERPLATE_ROLES: set[str] = {
    "navigation", "banner", "contentinfo", "complementary",
    "menu", "menubar", "toolbar", "status", "search",
}

# Class/ID patterns suggesting boilerplate (case-insensitive)
BOILERPLATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)(footer|sidebar|cookie|banner|popup|modal|overlay|social|share|widget|ad[s_-]|promo|sponsor|newsletter|signup|menu|breadcrumb|pagination|related|recommend|comment)"),
]

# Patterns indicating hidden elements
HIDDEN_STYLE_PATTERNS: list[re.Pattern] = [
    re.compile(r"display\s*:\s*none"),
    re.compile(r"visibility\s*:\s*hidden"),
    re.compile(r"opacity\s*:\s*0(?:[;\s]|$)"),
    re.compile(r"height\s*:\s*0(?:px)?(?:[;\s]|$)"),
    re.compile(r"overflow\s*:\s*hidden.*height\s*:\s*0"),
]


# ============================================================================
# DOM Pruning
# ============================================================================


def prune_dom(html_content: str) -> str:
    """Strip elements that carry zero extraction value from HTML.

    This is the first stage of the preprocessing pipeline. Removes:
    - Script, style, noscript, SVG, canvas, iframe tags
    - Navigation bars, footers, sidebars (by tag, role, class/id)
    - Hidden elements (display:none, visibility:hidden)
    - Comment nodes
    - Tracking pixels and ad containers
    - Empty container divs

    Args:
        html_content: Raw HTML string.

    Returns:
        Pruned HTML string with boilerplate removed.
    """
    if not html_content or not html_content.strip():
        return ""

    try:
        tree = lxml_html.fromstring(html_content)
    except (etree.ParserError, etree.XMLSyntaxError):
        logger.warning("html_parse_failed", action="returning_raw")
        return html_content

    _remove_comments(tree)
    _remove_strip_tags(tree)
    _remove_boilerplate_elements(tree)
    _remove_hidden_elements(tree)
    _remove_empty_containers(tree)

    result = lxml_html.tostring(tree, encoding="unicode")
    logger.debug(
        "dom_pruned",
        original_len=len(html_content),
        pruned_len=len(result),
        reduction=f"{(1 - len(result) / max(len(html_content), 1)) * 100:.1f}%",
    )
    return result


def _remove_comments(tree: HtmlElement) -> None:
    """Remove all comment nodes from the tree."""
    for comment in tree.iter(etree.Comment):
        parent = comment.getparent()
        if parent is not None:
            parent.remove(comment)


def _remove_strip_tags(tree: HtmlElement) -> None:
    """Remove tags that are always noise (script, style, svg, etc.)."""
    for element in tree.iter():
        if isinstance(element.tag, str) and element.tag.lower() in STRIP_TAGS:
            parent = element.getparent()
            if parent is not None:
                parent.remove(element)


def _remove_boilerplate_elements(tree: HtmlElement) -> None:
    """Remove elements identified as boilerplate by tag, role, or class/id."""
    elements_to_remove = []

    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue

        # Check tag name
        if element.tag.lower() in BOILERPLATE_TAGS:
            elements_to_remove.append(element)
            continue

        # Check ARIA role
        role = element.get("role", "").lower()
        if role in BOILERPLATE_ROLES:
            elements_to_remove.append(element)
            continue

        # Check class and id patterns
        classes = element.get("class", "")
        element_id = element.get("id", "")
        combined = f"{classes} {element_id}"

        if any(pattern.search(combined) for pattern in BOILERPLATE_PATTERNS):
            # Don't remove if it contains substantial content (avoid false positives)
            text = element.text_content() or ""
            if len(text.strip()) < 500:  # Short content = likely boilerplate
                elements_to_remove.append(element)

    for element in elements_to_remove:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def _remove_hidden_elements(tree: HtmlElement) -> None:
    """Remove elements hidden via inline CSS."""
    elements_to_remove = []

    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue

        style = element.get("style", "")
        if style and any(p.search(style) for p in HIDDEN_STYLE_PATTERNS):
            elements_to_remove.append(element)
            continue

        # Check for aria-hidden
        if element.get("aria-hidden", "").lower() == "true":
            elements_to_remove.append(element)

    for element in elements_to_remove:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


def _remove_empty_containers(tree: HtmlElement) -> None:
    """Remove divs and spans that contain no meaningful text.

    These are typically layout wrappers, spacer elements, or cleared containers.
    Only removes if the element has no text and no meaningful children.
    """
    container_tags = {"div", "span", "section", "article"}
    elements_to_remove = []

    for element in tree.iter():
        if not isinstance(element.tag, str):
            continue
        if element.tag.lower() not in container_tags:
            continue

        text = (element.text_content() or "").strip()
        if not text and len(element) == 0:
            elements_to_remove.append(element)

    for element in elements_to_remove:
        parent = element.getparent()
        if parent is not None:
            parent.remove(element)


# ============================================================================
# HTML → Markdown Conversion
# ============================================================================


class _ArachneConverter(MarkdownConverter):
    """Custom markdownify converter with Arachne-specific handling.

    Enhancements over default markdownify:
    - Link-to-citation conversion (reduces inline noise for LLMs)
    - Better table handling
    - Image alt text preservation
    - Stripping of class/id/data attributes from output
    """

    def __init__(self, use_citations: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.use_citations = use_citations
        self._citations: list[str] = []
        self._citation_map: dict[str, int] = {}

    def convert_a(self, el, text, convert_as_inline):
        """Convert links with optional citation mode.

        Citation mode: [text][1] with [1]: url appended as footnotes.
        This reduces inline noise and prevents LLMs from getting confused
        by long URLs mid-sentence (Crawl4AI pattern).
        """
        href = el.get("href", "")
        if not href or not text.strip():
            return text or ""

        if not self.use_citations:
            return f"[{text.strip()}]({href})"

        # Citation mode: deduplicate URLs
        if href not in self._citation_map:
            self._citation_map[href] = len(self._citations) + 1
            self._citations.append(href)

        ref_num = self._citation_map[href]
        return f"[{text.strip()}][{ref_num}]"

    def convert_img(self, el, text, convert_as_inline):
        """Preserve image references for vision model fallback."""
        alt = el.get("alt", "").strip()
        src = el.get("src", "")
        if not src:
            return ""
        return f"![{alt}]({src})"

    def convert_table(self, el, text, convert_as_inline):
        """Ensure tables convert cleanly to markdown tables."""
        # Let markdownify handle table conversion by default
        return f"\n\n{text}\n\n"

    def get_citations_footer(self) -> str:
        """Generate the citations footnote block."""
        if not self._citations:
            return ""
        lines = [f"[{i + 1}]: {url}" for i, url in enumerate(self._citations)]
        return "\n\n" + "\n".join(lines)


def html_to_markdown(
    html_content: str,
    *,
    use_citations: bool = True,
) -> str:
    """Convert pruned HTML to clean, LLM-friendly Markdown.

    Preserves semantic structure (headings, lists, tables, links, images)
    while stripping all presentation noise (class names, IDs, data attrs).

    Args:
        html_content: Pruned HTML string.
        use_citations: If True, convert inline links to citation format
            [text][1] with footnotes. Reduces token waste on long URLs.

    Returns:
        Clean markdown string.
    """
    if not html_content or not html_content.strip():
        return ""

    converter = _ArachneConverter(
        use_citations=use_citations,
        heading_style="atx",  # # Heading style
        bullets="-",
        strong_em_symbol="*",
        convert=["a", "img", "table", "thead", "tbody", "tr", "th", "td",
                 "h1", "h2", "h3", "h4", "h5", "h6",
                 "p", "br", "hr", "blockquote", "pre", "code",
                 "ul", "ol", "li", "b", "strong", "i", "em",
                 "dl", "dt", "dd", "sup", "sub"],
    )

    markdown = converter.convert(html_content)

    # Append citation footnotes if in citation mode
    if use_citations:
        markdown += converter.get_citations_footer()

    # Post-processing: clean up excessive whitespace
    markdown = _clean_markdown(markdown)

    return markdown


def _clean_markdown(markdown: str) -> str:
    """Post-process markdown to remove noise and excessive whitespace."""
    # Collapse multiple blank lines to maximum two
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)

    # Remove trailing whitespace on each line
    markdown = "\n".join(line.rstrip() for line in markdown.split("\n"))

    # Unescape HTML entities that survived conversion
    markdown = unescape(markdown)

    # Remove zero-width characters and other invisible Unicode
    markdown = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", markdown)

    return markdown.strip()


# ============================================================================
# Content Scoring
# ============================================================================


def score_content(html_content: str) -> list[ScoredBlock]:
    """Score HTML blocks by likely content relevance.

    Uses text density, link density, and position heuristics to rank
    blocks from most content-bearing to most boilerplate.

    Scoring factors:
        - Text density: paragraphs with high text-to-tag ratio score higher
        - Link density: high link-to-text ratio indicates navigation (lower score)
        - Position: center/main content scores higher than edge positions
        - Tag semantics: <article>, <main> get bonus; <aside> gets penalty

    Args:
        html_content: Pruned HTML (after prune_dom).

    Returns:
        List of ScoredBlock sorted by score descending.
    """
    if not html_content or not html_content.strip():
        return []

    try:
        tree = lxml_html.fromstring(html_content)
    except (etree.ParserError, etree.XMLSyntaxError):
        return []

    blocks: list[ScoredBlock] = []
    content_tags = {"p", "article", "main", "section", "div", "td", "li",
                    "blockquote", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}

    for position, element in enumerate(tree.iter()):
        if not isinstance(element.tag, str):
            continue
        if element.tag.lower() not in content_tags:
            continue

        text = (element.text_content() or "").strip()
        if len(text) < 25:  # Skip very short blocks
            continue

        # Calculate link density
        links = element.findall(".//a")
        link_text_len = sum(len((a.text_content() or "").strip()) for a in links)
        link_density = link_text_len / max(len(text), 1)

        # Calculate text density (text chars vs total element size)
        element_html = lxml_html.tostring(element, encoding="unicode")
        text_density = len(text) / max(len(element_html), 1)

        # Base score from text density (higher = more likely content)
        score = text_density * 0.5

        # Link density penalty (navigation has high link density)
        score -= link_density * 0.3

        # Tag-based bonuses/penalties
        tag = element.tag.lower()
        if tag in ("article", "main"):
            score += 0.25
        elif tag in ("p", "blockquote"):
            score += 0.15
        elif tag in ("h1", "h2", "h3"):
            score += 0.10
        elif tag == "aside":
            score -= 0.20

        # Length bonus (longer blocks are more likely content)
        if len(text) > 200:
            score += 0.10
        if len(text) > 500:
            score += 0.05

        score = max(0.0, min(1.0, score))

        blocks.append(ScoredBlock(
            content=text,
            score=score,
            tag=tag,
            position=position,
            char_count=len(text),
            link_density=link_density,
        ))

    blocks.sort(key=lambda b: b.score, reverse=True)
    return blocks


# ============================================================================
# BM25 Content Filtering (optional query-relevant extraction)
# ============================================================================


def _bm25_filter(
    blocks: list[ScoredBlock],
    query: str,
    top_k: int = 10,
) -> list[ScoredBlock]:
    """Filter content blocks by relevance to a query using BM25.

    Used when the user provides a query or extraction schema to focus
    the LLM on the most relevant page sections.

    Args:
        blocks: Scored content blocks from score_content().
        query: Search query or schema description.
        top_k: Number of top blocks to return.

    Returns:
        Filtered and re-ranked blocks.
    """
    if not blocks or not query:
        return blocks

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.warning("rank_bm25_not_installed", action="skipping_filter")
        return blocks

    # Tokenize blocks and query
    corpus = [block.content.lower().split() for block in blocks]
    query_tokens = query.lower().split()

    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query_tokens)

    # Combine BM25 score with content score
    for block, bm25_score in zip(blocks, scores):
        # Normalize BM25 score to 0-1 range
        max_score = max(scores) if max(scores) > 0 else 1
        normalized = bm25_score / max_score
        # Weighted combination: 60% content score, 40% BM25 relevance
        block.score = block.score * 0.6 + normalized * 0.4

    blocks.sort(key=lambda b: b.score, reverse=True)
    return blocks[:top_k]


# ============================================================================
# Full Preprocessing Pipeline
# ============================================================================


def preprocess(
    html_content: str,
    *,
    query: str | None = None,
    use_citations: bool = True,
    extract_metadata: bool = True,
) -> PreprocessResult:
    """Full preprocessing pipeline: prune → score → convert → filter.

    This is the main entry point for the preprocessing module. Takes raw
    HTML and produces clean, token-efficient Markdown ready for LLM extraction.

    Args:
        html_content: Raw HTML string from the crawl.
        query: Optional query/schema description for BM25 filtering.
        use_citations: Convert inline links to citation format.
        extract_metadata: Use trafilatura for metadata extraction.

    Returns:
        PreprocessResult with markdown, metrics, and optional metadata.
    """
    raw_len = len(html_content) if html_content else 0

    if not html_content or not html_content.strip():
        return PreprocessResult(
            markdown="",
            raw_char_count=0,
            pruned_char_count=0,
            markdown_char_count=0,
            reduction_ratio=0.0,
        )

    # Phase 1: DOM pruning
    pruned_html = prune_dom(html_content)
    pruned_len = len(pruned_html)

    # Phase 2: Content scoring and optional filtering
    if query:
        scored_blocks = score_content(pruned_html)
        filtered_blocks = _bm25_filter(scored_blocks, query)
        if filtered_blocks:
            # Reconstruct HTML from top-scored blocks for conversion
            # (fall through to full conversion if no blocks match)
            content_parts = [block.content for block in filtered_blocks]
            # Convert filtered content directly
            markdown = "\n\n".join(content_parts)
        else:
            markdown = html_to_markdown(pruned_html, use_citations=use_citations)
    else:
        # No query filter — convert entire pruned document
        markdown = html_to_markdown(pruned_html, use_citations=use_citations)

    markdown_len = len(markdown)

    # Phase 3: Metadata extraction (optional, via trafilatura)
    metadata: dict = {}
    if extract_metadata:
        metadata = _extract_metadata(html_content)

    # Content hash for deduplication / change detection
    content_hash = hashlib.sha256(markdown.encode()).hexdigest()

    reduction = raw_len / max(markdown_len, 1)

    logger.info(
        "preprocessing_complete",
        raw_chars=raw_len,
        pruned_chars=pruned_len,
        markdown_chars=markdown_len,
        reduction_ratio=f"{reduction:.1f}x",
        has_metadata=bool(metadata),
    )

    return PreprocessResult(
        markdown=markdown,
        raw_char_count=raw_len,
        pruned_char_count=pruned_len,
        markdown_char_count=markdown_len,
        reduction_ratio=reduction,
        metadata=metadata,
        content_hash=content_hash,
    )


def _extract_metadata(html_content: str) -> dict:
    """Extract page metadata using trafilatura.

    Trafilatura provides rich metadata extraction for free: title, author,
    date, description, sitename, categories, tags, and language detection.

    Uses bare_extraction() for raw Python dicts directly into the pipeline.
    """
    try:
        from trafilatura import bare_extraction

        result = bare_extraction(html_content, include_comments=False)
        if result is None:
            return {}

        # Extract the metadata fields we care about
        metadata: dict = {}
        for key in ("title", "author", "date", "description", "sitename",
                     "categories", "tags", "language", "url"):
            value = result.get(key)
            if value:
                metadata[key] = value

        return metadata

    except ImportError:
        logger.debug("trafilatura_not_installed", action="skipping_metadata")
        return {}
    except Exception as e:
        logger.warning("metadata_extraction_failed", error=str(e))
        return {}
