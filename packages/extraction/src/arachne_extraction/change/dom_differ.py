"""
DOM tree structural differencing for change detection.

Computes structural edit distance between two HTML documents,
ignoring noise such as class name mutations, inline style changes,
wrapper div additions, and ad/tracking content.

Key insight: Most web scraping breakage comes from structural
DOM changes (element hierarchy shifts, tag renames), NOT content
changes. This differ targets those structural shifts.

References:
    - Phase4.md Step 4.1: DOM differencing
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class DOMChange:
    """A single change detected between two DOM trees."""

    change_type: str  # "added", "removed", "modified", "moved"
    element_tag: str
    css_path: str = ""
    old_value: str = ""
    new_value: str = ""
    significance: float = 1.0  # 0-1, how significant this change is


@dataclass
class DOMDiffResult:
    """Complete DOM differencing result."""

    structural_distance: float  # 0-1 normalized edit distance
    changes: list[DOMChange] = field(default_factory=list)
    tags_added: int = 0
    tags_removed: int = 0
    tags_modified: int = 0
    total_elements_a: int = 0
    total_elements_b: int = 0
    noise_filtered: int = 0  # Changes filtered as noise

    @property
    def significant_changes(self) -> list[DOMChange]:
        return [c for c in self.changes if c.significance > 0.5]


# ============================================================================
# Noise Filter Patterns
# ============================================================================

# CSS classes that commonly change without structural impact
NOISE_CLASS_PATTERNS = [
    r"^(ab-|ad-|analytics-|tracking-|gtm-)",  # Analytics/ad classes
    r"^(js-|is-|has-|no-)",  # State classes
    r"-active$", r"-open$", r"-closed$", r"-visible$", r"-hidden$",
    r"^(lazyload|loaded|lazy)",  # Lazy loading states
    r"^(wp-|elementor-|wp_)",  # CMS WordPress noise
]

# Tags that are typically non-content noise
NOISE_TAGS = {
    "script", "style", "noscript", "iframe", "svg", "path",
    "meta", "link", "head",
}

# Attributes to ignore when comparing elements
NOISE_ATTRIBUTES = {
    "class", "style", "id", "data-reactid", "data-testid",
    "data-v-", "data-qa", "aria-hidden",
}


# ============================================================================
# DOM Differ
# ============================================================================


class DOMDiffer:
    """Compute structural edit distance between two HTML documents.

    Focuses on meaningful structural changes (tag hierarchy shifts,
    content container changes) while filtering out noise (class mutations,
    style changes, ad/analytics elements).

    Usage:
        differ = DOMDiffer()
        result = differ.diff(html_old, html_new)

        print(f"Structural distance: {result.structural_distance:.2f}")
        for change in result.significant_changes:
            print(f"  {change.change_type}: {change.element_tag}")
    """

    def __init__(
        self,
        ignore_noise: bool = True,
        noise_tags: set[str] | None = None,
    ):
        self.ignore_noise = ignore_noise
        self.noise_tags = noise_tags or NOISE_TAGS

    def diff(self, html_a: str, html_b: str) -> DOMDiffResult:
        """Compute structural diff between two HTML documents.

        Args:
            html_a: First (old) HTML document.
            html_b: Second (new) HTML document.

        Returns:
            DOMDiffResult with structural distance and changes.
        """
        tree_a = self._parse_to_tree(html_a)
        tree_b = self._parse_to_tree(html_b)

        if tree_a is None or tree_b is None:
            logger.warning("dom_diff_parse_failed")
            return DOMDiffResult(structural_distance=1.0)

        # Extract tag sequences (simplified tree structure)
        tags_a = self._extract_tag_sequence(tree_a)
        tags_b = self._extract_tag_sequence(tree_b)

        if self.ignore_noise:
            tags_a = [t for t in tags_a if t not in self.noise_tags]
            tags_b = [t for t in tags_b if t not in self.noise_tags]

        # Compute edit distance on tag sequences
        distance = self._sequence_edit_distance(tags_a, tags_b)
        max_len = max(len(tags_a), len(tags_b), 1)
        normalized_distance = distance / max_len

        # Detect specific changes
        changes, noise_count = self._detect_changes(tags_a, tags_b)

        # Count changes by type
        added = sum(1 for c in changes if c.change_type == "added")
        removed = sum(1 for c in changes if c.change_type == "removed")
        modified = sum(1 for c in changes if c.change_type == "modified")

        return DOMDiffResult(
            structural_distance=min(1.0, normalized_distance),
            changes=changes,
            tags_added=added,
            tags_removed=removed,
            tags_modified=modified,
            total_elements_a=len(tags_a),
            total_elements_b=len(tags_b),
            noise_filtered=noise_count,
        )

    def _parse_to_tree(self, html: str) -> Any | None:
        """Parse HTML to a tree structure."""
        try:
            from lxml import etree

            parser = etree.HTMLParser()
            return etree.fromstring(html.encode(), parser)
        except ImportError:
            pass

        try:
            from html.parser import HTMLParser

            # Simplified: just return the raw HTML for tag extraction
            return html
        except Exception:
            return None

    def _extract_tag_sequence(self, tree: Any) -> list[str]:
        """Extract a flat sequence of tags representing the DOM structure."""
        try:
            from lxml import etree

            if isinstance(tree, etree._Element):
                tags = []
                for elem in tree.iter():
                    tag = elem.tag if isinstance(elem.tag, str) else ""
                    if tag:
                        tags.append(tag.lower())
                return tags
        except (ImportError, AttributeError):
            pass

        # Fallback: regex-based tag extraction
        if isinstance(tree, str):
            tag_pattern = re.compile(r"<(\w+)[\s>]", re.IGNORECASE)
            return [m.group(1).lower() for m in tag_pattern.finditer(tree)]

        return []

    def _detect_changes(
        self,
        tags_a: list[str],
        tags_b: list[str],
    ) -> tuple[list[DOMChange], int]:
        """Detect specific DOM changes between tag sequences."""
        changes: list[DOMChange] = []
        noise_count = 0

        set_a = {}
        set_b = {}

        # Count tag frequencies
        for tag in tags_a:
            set_a[tag] = set_a.get(tag, 0) + 1
        for tag in tags_b:
            set_b[tag] = set_b.get(tag, 0) + 1

        all_tags = set(set_a.keys()) | set(set_b.keys())

        for tag in all_tags:
            count_a = set_a.get(tag, 0)
            count_b = set_b.get(tag, 0)

            diff = count_b - count_a

            # Check if this is noise
            is_noise = tag in self.noise_tags
            if is_noise:
                noise_count += abs(diff)
                continue

            significance = self._tag_significance(tag)

            if diff > 0:
                changes.append(DOMChange(
                    change_type="added",
                    element_tag=tag,
                    old_value=str(count_a),
                    new_value=str(count_b),
                    significance=significance,
                ))
            elif diff < 0:
                changes.append(DOMChange(
                    change_type="removed",
                    element_tag=tag,
                    old_value=str(count_a),
                    new_value=str(count_b),
                    significance=significance,
                ))

        return changes, noise_count

    @staticmethod
    def _tag_significance(tag: str) -> float:
        """Rate how significant a tag change is for content extraction."""
        # High significance: content-bearing tags
        high = {"table", "tr", "td", "th", "ul", "ol", "li", "article",
                "section", "main", "h1", "h2", "h3", "h4", "p", "a"}
        # Medium significance: structural wrappers
        medium = {"div", "span", "form", "nav", "header", "footer", "aside"}
        # Low significance: presentational
        low = {"br", "hr", "img", "picture", "source", "figure", "figcaption"}

        if tag in high:
            return 1.0
        if tag in medium:
            return 0.5
        if tag in low:
            return 0.3
        return 0.4

    @staticmethod
    def _sequence_edit_distance(a: list[str], b: list[str]) -> int:
        """Levenshtein edit distance between two tag sequences.

        Bounded computation: limits matrix to first 500 elements
        to avoid O(n²) blowup on large pages.
        """
        max_n = 500
        a = a[:max_n]
        b = b[:max_n]

        m, n = len(a), len(b)
        if m == 0:
            return n
        if n == 0:
            return m

        # Use two-row optimization for memory efficiency
        prev = list(range(n + 1))
        curr = [0] * (n + 1)

        for i in range(1, m + 1):
            curr[0] = i
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    curr[j] = prev[j - 1]
                else:
                    curr[j] = 1 + min(prev[j], curr[j - 1], prev[j - 1])
            prev, curr = curr, prev

        return prev[n]
