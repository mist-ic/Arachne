"""
arachne-extraction — AI-first extraction engine.

Provides the complete extraction pipeline: HTML preprocessing, LLM-based
structured extraction, multi-model routing, auto-schema discovery,
and CAPTCHA solving.

Modules:
    preprocessor    — DOM pruning + HTML→Markdown conversion
    chunker         — Context-aware markdown chunking
    llm_extractor   — instructor/Pydantic schema-bound extraction
    model_router    — Multi-model routing with cost/accuracy tradeoffs
    schema_discovery — Auto-schema discovery for unknown sites
    captcha/        — Local and external CAPTCHA solving
"""

from arachne_extraction.preprocessor import preprocess, prune_dom, html_to_markdown
from arachne_extraction.chunker import chunk_markdown
from arachne_extraction.llm_extractor import LLMExtractor
from arachne_extraction.model_router import ExtractionRouter

__all__ = [
    "preprocess",
    "prune_dom",
    "html_to_markdown",
    "chunk_markdown",
    "LLMExtractor",
    "ExtractionRouter",
]
