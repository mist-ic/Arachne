"""
Crop extractor — extracts text and data from individual screenshot segments.

After SAM 3 segments the page and RF-DETR classifies each region, this module
crops individual elements from the original screenshot and sends each to a
vision-language model (Qwen3-VL / GPT-5) for focused text extraction.

The key insight: asking a VLM to extract data from a small, focused crop
(e.g., a single product card) is more accurate and cheaper than sending
the entire full-page screenshot.

References:
    - Research.md §2.2: Per-segment extraction
    - Phase4.md Step 2.3: Segment cropping and individual extraction
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import structlog

from arachne_extraction.vision.rfdetr_detector import DetectedElement
from arachne_extraction.vision.sam_segmenter import BoundingBox

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class CropExtractionResult:
    """Extraction result from a single cropped segment."""

    element: DetectedElement
    extracted_data: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    confidence: float = 0.0
    model_used: str = ""
    error: str | None = None


@dataclass
class AssemblyResult:
    """Final assembled result from all crop extractions."""

    entities: list[dict[str, Any]] = field(default_factory=list)
    total_crops: int = 0
    successful_crops: int = 0
    failed_crops: int = 0
    total_inference_ms: int = 0


# ============================================================================
# Prompt Templates for Focused Extraction
# ============================================================================


CROP_PROMPTS: dict[str, str] = {
    "product_card": (
        "Extract ALL product information visible in this image: "
        "product name/title, price (if visible), rating, description, "
        "availability status, and any other attributes."
    ),
    "price_tag": (
        "Extract the exact price shown in this image. Include currency "
        "symbol if visible. Return as a number."
    ),
    "product_title": (
        "Extract the exact product name or title shown in this image."
    ),
    "rating_stars": (
        "Extract the rating shown in this image. Return the numeric rating "
        "and the maximum possible rating (e.g., 4.5 out of 5)."
    ),
    "product_image": (
        "Describe the product shown in this image. Include color, brand "
        "name if visible, and notable visual features."
    ),
    "description_text": (
        "Extract ALL text visible in this image. Preserve formatting "
        "and structure."
    ),
    "table_row": (
        "Extract all data from this table row. Return as key-value pairs."
    ),
    "table_header": (
        "Extract all column headers from this table header row."
    ),
    "list_item": (
        "Extract the complete content of this list item."
    ),
    "search_result": (
        "Extract all information from this search result: title, URL, "
        "description snippet, and any metadata."
    ),
    "review": (
        "Extract the review content: reviewer name, rating, review text, "
        "date if visible."
    ),
    "specification": (
        "Extract the specification data: attribute name and value."
    ),
    "unknown": (
        "Extract all text and data visible in this image. Describe what "
        "type of content this appears to be."
    ),
}


# ============================================================================
# Crop Extractor
# ============================================================================


class CropExtractor:
    """Extract text and data from individual screenshot crops.

    Takes detected UI elements and their bounding boxes, crops each
    from the original screenshot, and sends to a VLM for focused
    extraction.

    Usage:
        extractor = CropExtractor(
            ollama_base_url="http://localhost:11434",
        )

        results = await extractor.extract_crops(
            image=screenshot_bytes,
            elements=detection_result.content_elements,
        )

        for result in results:
            print(f"{result.element.element_type}: {result.extracted_data}")
    """

    def __init__(
        self,
        model: str = "qwen3-vl",
        ollama_base_url: str = "http://localhost:11434",
        remote_model: str | None = None,
        api_key: str | None = None,
    ):
        """Initialize the crop extractor.

        Args:
            model: Local Ollama vision model name.
            ollama_base_url: Ollama server URL.
            remote_model: Remote vision model (e.g., "openai/gpt-5").
            api_key: API key for remote model.
        """
        self.model = model
        self.ollama_base_url = ollama_base_url
        self.remote_model = remote_model
        self.api_key = api_key

    async def extract_crops(
        self,
        image: bytes,
        elements: list[DetectedElement],
        *,
        padding: int = 10,
    ) -> list[CropExtractionResult]:
        """Extract data from each detected element.

        Args:
            image: Full-page screenshot as PNG bytes.
            elements: Detected UI elements with bounding boxes.
            padding: Extra pixels around each crop for context.

        Returns:
            List of extraction results, one per element.
        """
        results = []

        for element in elements:
            try:
                # Crop the element from the screenshot
                crop_bytes = self._crop_element(image, element.box, padding)

                if crop_bytes is None:
                    results.append(CropExtractionResult(
                        element=element,
                        error="Failed to crop element",
                    ))
                    continue

                # Get the appropriate prompt
                prompt = CROP_PROMPTS.get(
                    element.element_type,
                    CROP_PROMPTS["unknown"],
                )

                # Extract using vision model
                extracted = await self._extract_single_crop(
                    crop_bytes, prompt, element.element_type,
                )

                results.append(CropExtractionResult(
                    element=element,
                    extracted_data=extracted.get("data", {}),
                    raw_text=extracted.get("raw_text", ""),
                    confidence=extracted.get("confidence", 0.0),
                    model_used=extracted.get("model", self.model),
                ))

            except Exception as e:
                logger.error(
                    "crop_extraction_error",
                    element_type=element.element_type,
                    error=str(e),
                )
                results.append(CropExtractionResult(
                    element=element,
                    error=str(e),
                ))

        return results

    async def _extract_single_crop(
        self,
        crop_bytes: bytes,
        prompt: str,
        element_type: str,
    ) -> dict:
        """Extract data from a single crop using vision model."""
        import base64

        img_b64 = base64.b64encode(crop_bytes).decode("utf-8")

        # Try local Ollama first
        try:
            import ollama

            response = ollama.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [img_b64],
                    },
                ],
                options={"temperature": 0.0},
            )

            raw_text = response.get("message", {}).get("content", "")

            return {
                "data": self._parse_extraction(raw_text, element_type),
                "raw_text": raw_text,
                "confidence": 0.7,  # Base confidence for local model
                "model": f"ollama/{self.model}",
            }

        except ImportError:
            pass
        except Exception as e:
            logger.debug("crop_ollama_failed", error=str(e))

        # Fallback to remote model
        if self.remote_model and self.api_key:
            try:
                import litellm

                litellm.api_key = self.api_key

                response = litellm.completion(
                    model=self.remote_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{img_b64}",
                                    },
                                },
                            ],
                        },
                    ],
                )

                raw_text = response.choices[0].message.content or ""

                return {
                    "data": self._parse_extraction(raw_text, element_type),
                    "raw_text": raw_text,
                    "confidence": 0.85,
                    "model": self.remote_model,
                }

            except Exception as e:
                logger.warning("crop_remote_failed", error=str(e))

        return {"data": {}, "raw_text": "", "confidence": 0.0, "model": "none"}

    def _crop_element(
        self,
        image: bytes,
        box: BoundingBox,
        padding: int = 10,
    ) -> bytes | None:
        """Crop a bounding box region from the screenshot."""
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(image)).convert("RGB")
            img_width, img_height = img.size

            # Apply padding with bounds checking
            x1 = max(0, box.x - padding)
            y1 = max(0, box.y - padding)
            x2 = min(img_width, box.x2 + padding)
            y2 = min(img_height, box.y2 + padding)

            # Ensure minimum crop size
            if x2 - x1 < 10 or y2 - y1 < 10:
                return None

            crop = img.crop((x1, y1, x2, y2))

            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            return buf.getvalue()

        except ImportError:
            logger.warning("crop_pillow_not_available")
            return None
        except Exception as e:
            logger.error("crop_failed", error=str(e))
            return None

    @staticmethod
    def _parse_extraction(raw_text: str, element_type: str) -> dict:
        """Parse raw VLM text response into structured data.

        Attempts JSON parsing first, then falls back to simple
        key-value extraction for common element types.
        """
        import json
        import re

        # Try JSON extraction
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try raw JSON
        try:
            return json.loads(raw_text.strip())
        except (json.JSONDecodeError, ValueError):
            pass

        # Fallback: return as typed content
        return {
            "type": element_type,
            "content": raw_text.strip(),
        }

    @staticmethod
    def assemble_entities(
        crop_results: list[CropExtractionResult],
        *,
        proximity_threshold: int = 50,
    ) -> AssemblyResult:
        """Assemble individual crop extractions into entity groupings.

        Groups crops that belong to the same entity based on spatial
        proximity (e.g., a product card's title, price, and image are
        near each other → they belong to the same product).

        Args:
            crop_results: List of crop extraction results.
            proximity_threshold: Max pixel distance between elements
                                 to be considered part of the same entity.

        Returns:
            AssemblyResult with grouped entities.
        """
        successful = [r for r in crop_results if r.error is None and r.extracted_data]
        failed = [r for r in crop_results if r.error is not None]

        if not successful:
            return AssemblyResult(
                total_crops=len(crop_results),
                failed_crops=len(failed),
            )

        # Group by spatial proximity
        groups: list[list[CropExtractionResult]] = []
        used = set()

        for i, result in enumerate(successful):
            if i in used:
                continue

            group = [result]
            used.add(i)

            for j, other in enumerate(successful):
                if j in used or j <= i:
                    continue

                # Check proximity
                dist = _box_distance(result.element.box, other.element.box)
                if dist <= proximity_threshold:
                    group.append(other)
                    used.add(j)

            groups.append(group)

        # Merge each group into a single entity
        entities = []
        for group in groups:
            entity: dict = {}
            for result in group:
                entity[result.element.element_type] = result.extracted_data
            entities.append(entity)

        return AssemblyResult(
            entities=entities,
            total_crops=len(crop_results),
            successful_crops=len(successful),
            failed_crops=len(failed),
        )


def _box_distance(a: BoundingBox, b: BoundingBox) -> float:
    """Calculate the minimum distance between two bounding boxes."""
    # Horizontal distance
    if a.x2 < b.x:
        dx = b.x - a.x2
    elif b.x2 < a.x:
        dx = a.x - b.x2
    else:
        dx = 0

    # Vertical distance
    if a.y2 < b.y:
        dy = b.y - a.y2
    elif b.y2 < a.y:
        dy = a.y - b.y2
    else:
        dy = 0

    return (dx ** 2 + dy ** 2) ** 0.5
