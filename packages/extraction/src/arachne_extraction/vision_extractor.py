"""
Vision-based structured extraction via screenshot + VLM.

When HTML-based extraction fails (low confidence, validation errors, obfuscated
DOM), this fallback captures a screenshot and feeds it to a vision-capable model.
The model interprets the page as a human sees it — bypassing anti-scraping DOM
corruption, Canvas/SVG rendering, Shadow DOMs, and deep SPA structures.

Supports:
    - Local: Qwen3-VL via Ollama (free, GPU-accelerated)
    - Remote: GPT-5 / Gemini 3 Pro Vision (higher accuracy, API cost)

References:
    - Research.md §2.2: Vision extraction — "NOT a gimmick"
    - Phase4.md Step 1: Vision-Based Extraction Fallback
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class VisionExtractionOutput:
    """Result of a vision-based extraction attempt.

    Mirrors ExtractionOutput but includes vision-specific metadata
    like screenshot dimensions and model-specific parameters.
    """

    data: BaseModel | None  # The extracted Pydantic model instance
    model_used: str  # e.g., "ollama/qwen3-vl", "openai/gpt-5"
    tokens_input: int = 0
    tokens_output: int = 0
    estimated_cost_usd: float = 0.0
    latency_ms: int = 0
    extraction_method: str = "vision"
    confidence: float = 0.0
    screenshot_size_bytes: int = 0
    screenshot_width: int = 0
    screenshot_height: int = 0
    error: str | None = None


class VisionExtractionConfig(BaseModel):
    """Configuration for vision-based extraction."""

    # Model selection
    local_model: str = Field(
        default="qwen3-vl",
        description="Ollama model for local vision extraction",
    )
    remote_model: str = Field(
        default="gemini/gemini-2.5-flash",
        description="Remote model for high-accuracy vision extraction",
    )
    prefer_local: bool = Field(
        default=True,
        description="Try local model first before remote",
    )

    # Ollama connection
    ollama_base_url: str = "http://localhost:11434"

    # Remote API
    api_key: str | None = None

    # Extraction parameters
    temperature: float = 0.0
    max_tokens: int = 4096

    # Confidence threshold for accepting vision results
    min_confidence: float = 0.3


# ============================================================================
# Vision Prompt Templates
# ============================================================================


VISION_SYSTEM_PROMPT = """You are a precise visual data extraction assistant. You are analyzing a screenshot of a web page. Your task is to extract structured data visible in the image.

Rules:
1. ONLY extract data that is VISUALLY PRESENT in the screenshot
2. Read text, numbers, prices, dates exactly as they appear
3. If a field's value is not visible in the image, return null
4. For numeric fields, extract numbers without currency symbols unless specified
5. For dates, use ISO 8601 format when possible
6. Pay attention to tables, lists, cards, and structured layouts
7. Ignore navigation menus, footers, ads, and boilerplate elements"""

VISION_USER_PROMPT = """Extract structured data from this web page screenshot.

Source URL: {url}

Look carefully at the screenshot and extract ALL fields defined in the schema.
Focus on the main content area. Extract data exactly as it appears visually."""


# ============================================================================
# Vision Extractor
# ============================================================================


class VisionExtractor:
    """Extract structured data from page screenshots using vision models.

    Uses instructor for schema-bound extraction with vision-capable models.
    Supports both local (Ollama) and remote (OpenAI/Gemini/Anthropic) models.

    Usage:
        extractor = VisionExtractor(config=VisionExtractionConfig(
            ollama_base_url="http://localhost:11434",
        ))

        class Product(BaseModel):
            name: str
            price: float

        result = await extractor.extract_from_screenshot(
            screenshot=png_bytes,
            schema=Product,
            url="https://example.com/product",
        )
    """

    def __init__(self, config: VisionExtractionConfig | None = None):
        self.config = config or VisionExtractionConfig()

    async def extract_from_screenshot(
        self,
        screenshot: bytes,
        schema: type[T],
        *,
        url: str = "unknown",
        use_local: bool | None = None,
    ) -> VisionExtractionOutput:
        """Extract structured data from a screenshot using a vision model.

        Args:
            screenshot: PNG screenshot bytes.
            schema: Pydantic model class defining the extraction target.
            url: Source URL for context.
            use_local: Force local or remote model. If None, uses config preference.

        Returns:
            VisionExtractionOutput with extracted data.
        """
        start_time = time.monotonic()
        prefer_local = use_local if use_local is not None else self.config.prefer_local

        # Get screenshot dimensions for metadata
        width, height = self._get_image_dimensions(screenshot)

        if prefer_local:
            # Try local model first
            result = await self._extract_ollama(screenshot, schema, url)
            if result.data is not None and result.confidence >= self.config.min_confidence:
                result.screenshot_size_bytes = len(screenshot)
                result.screenshot_width = width
                result.screenshot_height = height
                result.latency_ms = int((time.monotonic() - start_time) * 1000)
                return result

            # Fall back to remote if local fails
            if self.config.api_key:
                logger.info(
                    "vision_local_fallback_to_remote",
                    local_confidence=result.confidence,
                    local_model=self.config.local_model,
                )
                result = await self._extract_remote(screenshot, schema, url)
        else:
            # Use remote model directly
            result = await self._extract_remote(screenshot, schema, url)

        result.screenshot_size_bytes = len(screenshot)
        result.screenshot_width = width
        result.screenshot_height = height
        result.latency_ms = int((time.monotonic() - start_time) * 1000)
        return result

    async def _extract_ollama(
        self,
        screenshot: bytes,
        schema: type[T],
        url: str,
    ) -> VisionExtractionOutput:
        """Extract using local Ollama vision model (Qwen3-VL)."""
        model_name = self.config.local_model

        try:
            import ollama

            # Encode screenshot as base64
            img_b64 = base64.b64encode(screenshot).decode("utf-8")

            user_prompt = VISION_USER_PROMPT.format(url=url)

            logger.debug(
                "vision_ollama_call",
                model=model_name,
                screenshot_bytes=len(screenshot),
            )

            # Call Ollama with vision
            response = ollama.chat(
                model=model_name,
                messages=[
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": user_prompt,
                        "images": [img_b64],
                    },
                ],
                options={
                    "temperature": self.config.temperature,
                    "num_predict": self.config.max_tokens,
                },
            )

            # Parse the response into the schema
            raw_text = response.get("message", {}).get("content", "")
            result = self._parse_response_to_schema(raw_text, schema)

            if result is not None:
                from arachne_extraction.llm_extractor import _calculate_confidence

                confidence = _calculate_confidence(result)
            else:
                confidence = 0.0

            # Extract token usage
            eval_count = response.get("eval_count", 0)
            prompt_eval_count = response.get("prompt_eval_count", 0)

            return VisionExtractionOutput(
                data=result,
                model_used=f"ollama/{model_name}",
                tokens_input=prompt_eval_count,
                tokens_output=eval_count,
                estimated_cost_usd=0.0,  # Local models are free
                confidence=confidence,
            )

        except ImportError:
            logger.warning("vision_ollama_not_available", reason="ollama package not installed")
            return VisionExtractionOutput(
                data=None,
                model_used=f"ollama/{model_name}",
                confidence=0.0,
                error="ollama package not installed",
            )
        except Exception as e:
            logger.error("vision_ollama_error", error=str(e), model=model_name)
            return VisionExtractionOutput(
                data=None,
                model_used=f"ollama/{model_name}",
                confidence=0.0,
                error=str(e),
            )

    async def _extract_remote(
        self,
        screenshot: bytes,
        schema: type[T],
        url: str,
    ) -> VisionExtractionOutput:
        """Extract using remote vision model via LiteLLM + instructor."""
        model = self.config.remote_model

        try:
            import instructor
            import litellm

            if self.config.api_key:
                litellm.api_key = self.config.api_key

            client = instructor.from_litellm(litellm.completion)

            # Encode screenshot as base64 data URI
            img_b64 = base64.b64encode(screenshot).decode("utf-8")
            image_url = f"data:image/png;base64,{img_b64}"

            user_prompt = VISION_USER_PROMPT.format(url=url)

            logger.debug(
                "vision_remote_call",
                model=model,
                screenshot_bytes=len(screenshot),
            )

            result = client.chat.completions.create(
                model=model,
                response_model=schema,
                messages=[
                    {"role": "system", "content": VISION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_url},
                            },
                        ],
                    },
                ],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )

            # Calculate confidence
            from arachne_extraction.llm_extractor import _calculate_confidence

            confidence = _calculate_confidence(result) if result else 0.0

            # Extract usage
            usage: dict = {}
            if hasattr(result, "_raw_response"):
                raw = result._raw_response
                if hasattr(raw, "usage"):
                    usage = {
                        "prompt_tokens": getattr(raw.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(raw.usage, "completion_tokens", 0),
                    }

            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)

            from arachne_extraction.llm_extractor import _estimate_cost

            return VisionExtractionOutput(
                data=result,
                model_used=model,
                tokens_input=tokens_in,
                tokens_output=tokens_out,
                estimated_cost_usd=_estimate_cost(model, tokens_in, tokens_out),
                confidence=confidence,
            )

        except Exception as e:
            logger.error("vision_remote_error", error=str(e), model=model)
            return VisionExtractionOutput(
                data=None,
                model_used=model,
                confidence=0.0,
                error=str(e),
            )

    def _parse_response_to_schema(
        self,
        raw_text: str,
        schema: type[T],
    ) -> T | None:
        """Parse raw LLM text response into a Pydantic model.

        Attempts JSON extraction from the response text, then validates
        against the schema. Handles cases where the model wraps JSON
        in markdown code blocks.
        """
        import json
        import re

        # Try to extract JSON from the response
        # Models often wrap JSON in ```json ... ``` blocks
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Try the entire response as JSON
            json_str = raw_text.strip()

        try:
            data = json.loads(json_str)
            return schema.model_validate(data)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(
                "vision_parse_failed",
                error=str(e),
                response_preview=raw_text[:200],
            )
            return None

    @staticmethod
    def _get_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
        """Get width and height from PNG bytes without PIL dependency."""
        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(image_bytes))
            return img.size
        except ImportError:
            # Fallback: parse PNG header directly
            if image_bytes[:8] == b"\x89PNG\r\n\x1a\n" and len(image_bytes) >= 24:
                import struct

                width = struct.unpack(">I", image_bytes[16:20])[0]
                height = struct.unpack(">I", image_bytes[20:24])[0]
                return width, height
            return 0, 0


# ============================================================================
# Screenshot Capture Helper
# ============================================================================


async def capture_screenshot(
    url: str,
    *,
    minio_client=None,
    bucket: str = "arachne-screenshots",
    job_id: str | None = None,
    full_page: bool = True,
    viewport_width: int = 1920,
    viewport_height: int = 1080,
) -> tuple[bytes, str]:
    """Capture a full-page screenshot and store in MinIO.

    Uses the stealth browser backend from Phase 2's Evasion Router
    when available, falling back to basic browser launch.

    Args:
        url: Page URL to screenshot.
        minio_client: MinIO storage client.
        bucket: MinIO bucket name.
        job_id: Job ID for the storage path.
        full_page: Capture full scrollable page vs viewport only.
        viewport_width: Browser viewport width.
        viewport_height: Browser viewport height.

    Returns:
        Tuple of (screenshot_bytes, minio_reference).
    """
    logger.info("screenshot_capture_start", url=url, full_page=full_page)

    screenshot_bytes: bytes

    try:
        # Try to use the stealth browser backend (Phase 2)
        from arachne_anti_detection.browsers.backend import get_browser_backend

        browser = get_browser_backend()
        screenshot_bytes = await browser.screenshot(
            url=url,
            full_page=full_page,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
        )
    except (ImportError, Exception) as e:
        logger.warning(
            "screenshot_stealth_unavailable",
            reason=str(e),
            fallback="playwright",
        )
        # Fallback: use Playwright directly
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(
                    viewport={"width": viewport_width, "height": viewport_height},
                )
                await page.goto(url, wait_until="networkidle", timeout=30000)
                screenshot_bytes = await page.screenshot(full_page=full_page)
                await browser.close()
        except ImportError:
            logger.error("screenshot_no_browser_available")
            raise RuntimeError(
                "No browser backend available for screenshots. "
                "Install playwright: pip install playwright && playwright install"
            )

    # Store in MinIO
    ref = f"minio://{bucket}/{job_id or 'unknown'}/screenshot.png"
    if minio_client:
        await minio_client.put_object(ref, screenshot_bytes)
        logger.info(
            "screenshot_stored",
            ref=ref,
            size_bytes=len(screenshot_bytes),
        )

    return screenshot_bytes, ref
