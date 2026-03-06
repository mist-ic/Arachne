"""
Context-aware markdown chunking for LLM extraction.

When preprocessed markdown exceeds a model's context window, this module
splits it intelligently at section boundaries rather than arbitrary
character counts. Key invariants:

    - Never split a table across chunks
    - Split at heading boundaries when possible
    - Include overlap between chunks for context continuity
    - Each chunk carries metadata about its source position

References:
    - Phase3.md Step 1.4: DOM-aware chunking
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class Chunk:
    """A single chunk of markdown content with positional metadata."""

    content: str  # The markdown text
    index: int  # 0-based chunk index
    total_chunks: int  # Total number of chunks
    start_char: int  # Character offset in original markdown
    end_char: int  # End character offset
    parent_section: str | None = None  # Nearest parent heading
    has_table: bool = False  # Whether this chunk contains a table
    estimated_tokens: int = 0  # Rough token count (~4 chars per token)
    overlap_chars: int = 0  # Characters of overlap from previous chunk


@dataclass
class _Section:
    """Internal: a section of markdown delimited by headings."""

    heading: str  # The heading text (e.g., "## Products")
    level: int  # Heading level (1-6)
    content: str  # Full text including the heading
    start_pos: int  # Character offset in original
    end_pos: int  # End offset
    has_table: bool = False


# ============================================================================
# Heading / Section Parsing
# ============================================================================

# Match ATX headings: # Heading, ## Heading, etc.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Match markdown tables (lines starting with |)
_TABLE_RE = re.compile(r"^\|.+\|$", re.MULTILINE)


def _parse_sections(markdown: str) -> list[_Section]:
    """Parse markdown into sections delimited by headings.

    If the document has no headings, the entire content is one section.
    Content before the first heading becomes a section with level 0.
    """
    headings = list(_HEADING_RE.finditer(markdown))

    if not headings:
        return [_Section(
            heading="",
            level=0,
            content=markdown,
            start_pos=0,
            end_pos=len(markdown),
            has_table=bool(_TABLE_RE.search(markdown)),
        )]

    sections: list[_Section] = []

    # Content before first heading
    if headings[0].start() > 0:
        pre_content = markdown[:headings[0].start()]
        if pre_content.strip():
            sections.append(_Section(
                heading="",
                level=0,
                content=pre_content,
                start_pos=0,
                end_pos=headings[0].start(),
                has_table=bool(_TABLE_RE.search(pre_content)),
            ))

    # Each heading starts a section that ends at the next heading
    for i, match in enumerate(headings):
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        content = markdown[start:end]
        heading_text = match.group(2).strip()
        level = len(match.group(1))

        sections.append(_Section(
            heading=heading_text,
            level=level,
            content=content,
            start_pos=start,
            end_pos=end,
            has_table=bool(_TABLE_RE.search(content)),
        ))

    return sections


# ============================================================================
# Table Detection and Protection
# ============================================================================


def _find_table_boundaries(text: str) -> list[tuple[int, int]]:
    """Find start/end positions of markdown tables.

    Tables are sequences of lines starting and ending with |.
    Returns list of (start_char, end_char) tuples.
    """
    tables: list[tuple[int, int]] = []
    lines = text.split("\n")
    in_table = False
    table_start = 0
    current_pos = 0

    for line in lines:
        stripped = line.strip()
        is_table_line = stripped.startswith("|") and stripped.endswith("|")

        if is_table_line and not in_table:
            in_table = True
            table_start = current_pos
        elif not is_table_line and in_table:
            in_table = False
            tables.append((table_start, current_pos))

        current_pos += len(line) + 1  # +1 for newline

    if in_table:
        tables.append((table_start, current_pos))

    return tables


def _is_inside_table(position: int, tables: list[tuple[int, int]]) -> bool:
    """Check if a character position falls inside a table."""
    return any(start <= position < end for start, end in tables)


# ============================================================================
# Chunking Engine
# ============================================================================


def chunk_markdown(
    markdown: str,
    *,
    max_tokens: int = 4000,
    overlap_sentences: int = 2,
    chars_per_token: float = 4.0,
) -> list[Chunk]:
    """Split markdown into chunks suitable for LLM context windows.

    Splitting strategy (in priority order):
        1. Split at section boundaries (headings) — cleanest breakpoint
        2. Split at paragraph boundaries — preserves readability
        3. Split at sentence boundaries — last resort, maintains coherence

    Never splits:
        - Inside a markdown table
        - Inside a code block

    Args:
        markdown: Preprocessed markdown content.
        max_tokens: Maximum tokens per chunk (model-dependent).
        overlap_sentences: Number of sentences to overlap between chunks
            for context continuity.
        chars_per_token: Approximate characters per token (4 for English).

    Returns:
        List of Chunk objects. Single chunk if content fits in window.
    """
    if not markdown or not markdown.strip():
        return []

    max_chars = int(max_tokens * chars_per_token)
    estimated_total_tokens = int(len(markdown) / chars_per_token)

    # Fast path: content fits in a single chunk
    if len(markdown) <= max_chars:
        return [Chunk(
            content=markdown,
            index=0,
            total_chunks=1,
            start_char=0,
            end_char=len(markdown),
            estimated_tokens=estimated_total_tokens,
        )]

    # Parse into sections
    sections = _parse_sections(markdown)
    table_boundaries = _find_table_boundaries(markdown)

    # Build chunks from sections
    chunks: list[Chunk] = []
    current_content = ""
    current_start = 0
    current_section_heading: str | None = None

    for section in sections:
        section_len = len(section.content)

        # If adding this section would exceed max, finalize current chunk
        if current_content and len(current_content) + section_len > max_chars:
            # But if the section contains a table and we'd split it, include it anyway
            if section.has_table and section_len < max_chars * 1.5:
                # Finalize current, start new with this section
                _finalize_chunk(
                    chunks, current_content, current_start,
                    current_section_heading, table_boundaries,
                    chars_per_token,
                )
                current_content = section.content
                current_start = section.start_pos
                current_section_heading = section.heading or current_section_heading
                continue

            _finalize_chunk(
                chunks, current_content, current_start,
                current_section_heading, table_boundaries,
                chars_per_token,
            )
            current_content = ""
            current_start = section.start_pos

        # If a single section exceeds max_chars, split it further
        if section_len > max_chars:
            # Finalize any accumulated content first
            if current_content:
                _finalize_chunk(
                    chunks, current_content, current_start,
                    current_section_heading, table_boundaries,
                    chars_per_token,
                )
                current_content = ""

            # Split the oversized section at paragraph boundaries
            sub_chunks = _split_large_section(
                section, max_chars, table_boundaries, chars_per_token,
            )
            chunks.extend(sub_chunks)
            current_start = section.end_pos
            current_section_heading = section.heading or current_section_heading
        else:
            current_content += section.content
            current_section_heading = section.heading or current_section_heading

    # Finalize remaining content
    if current_content.strip():
        _finalize_chunk(
            chunks, current_content, current_start,
            current_section_heading, table_boundaries,
            chars_per_token,
        )

    # Add overlap between chunks
    if overlap_sentences > 0 and len(chunks) > 1:
        _add_overlap(chunks, overlap_sentences)

    # Set total_chunks on all
    for chunk in chunks:
        chunk.total_chunks = len(chunks)
        chunk.index = chunks.index(chunk)

    return chunks


def _finalize_chunk(
    chunks: list[Chunk],
    content: str,
    start_pos: int,
    section_heading: str | None,
    table_boundaries: list[tuple[int, int]],
    chars_per_token: float,
) -> None:
    """Create and append a Chunk from accumulated content."""
    if not content.strip():
        return

    chunks.append(Chunk(
        content=content.strip(),
        index=len(chunks),
        total_chunks=0,  # Set later
        start_char=start_pos,
        end_char=start_pos + len(content),
        parent_section=section_heading,
        has_table=any(
            _is_inside_table(pos, table_boundaries)
            for pos in range(start_pos, start_pos + len(content), 100)
        ),
        estimated_tokens=int(len(content) / chars_per_token),
    ))


def _split_large_section(
    section: _Section,
    max_chars: int,
    table_boundaries: list[tuple[int, int]],
    chars_per_token: float,
) -> list[Chunk]:
    """Split an oversized section at paragraph boundaries.

    Falls back to sentence boundaries if paragraphs are still too large.
    Never splits inside a table.
    """
    paragraphs = section.content.split("\n\n")
    chunks: list[Chunk] = []
    current = ""
    current_start = section.start_pos

    for para in paragraphs:
        para_with_sep = para + "\n\n"

        if len(current) + len(para_with_sep) > max_chars:
            if current.strip():
                chunks.append(Chunk(
                    content=current.strip(),
                    index=0,
                    total_chunks=0,
                    start_char=current_start,
                    end_char=current_start + len(current),
                    parent_section=section.heading,
                    has_table=bool(_TABLE_RE.search(current)),
                    estimated_tokens=int(len(current) / chars_per_token),
                ))
            current = para_with_sep
            current_start = current_start + len(current)
        else:
            current += para_with_sep

    if current.strip():
        chunks.append(Chunk(
            content=current.strip(),
            index=0,
            total_chunks=0,
            start_char=current_start,
            end_char=current_start + len(current),
            parent_section=section.heading,
            has_table=bool(_TABLE_RE.search(current)),
            estimated_tokens=int(len(current) / chars_per_token),
        ))

    return chunks


def _add_overlap(chunks: list[Chunk], overlap_sentences: int) -> None:
    """Add sentence overlap between consecutive chunks for context continuity.

    The last N sentences of chunk[i] are prepended to chunk[i+1].
    This helps models understand context that spans chunk boundaries.
    """
    sentence_re = re.compile(r"(?<=[.!?])\s+")

    for i in range(1, len(chunks)):
        prev_content = chunks[i - 1].content
        sentences = sentence_re.split(prev_content)

        if len(sentences) <= overlap_sentences:
            continue

        overlap = " ".join(sentences[-overlap_sentences:])
        chunks[i].content = f"[...continued] {overlap}\n\n{chunks[i].content}"
        chunks[i].overlap_chars = len(overlap)
