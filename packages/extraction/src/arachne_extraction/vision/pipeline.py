"""
Full SAM 3 + RF-DETR + VLM vision extraction pipeline orchestrator.

The most technically impressive feature: a genuine multi-model computer
vision pipeline applied to web scraping. No existing open-source scraping
tool implements this.

Pipeline:
    Full-page screenshot
        ↓
    SAM 3 — Promptable concept segmentation
        → "Segment all product cards" / "Segment all pricing elements"
        → Returns bounding boxes for each semantic concept
        ↓
    RF-DETR — Real-time object detection
        → Refines bounding boxes, classifies UI element types
        → Labels: price_tag, product_title, rating_stars, image, button
        ↓
    Crop individual segments from the screenshot
        ↓
    Qwen3-VL / GPT-5 Vision — Extract text from each crop
        ↓
    Assemble into structured JSON via instructor/Pydantic

References:
    - Research.md §2.2: "This demonstrates CV/ML engineering depth
      far beyond 'I called the OpenAI API.'"
    - Phase4.md Step 2: SAM 3 + RF-DETR Vision Pipeline
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

from arachne_extraction.vision.crop_extractor import (
    AssemblyResult,
    CropExtractor,
)
from arachne_extraction.vision.rfdetr_detector import (
    DetectionResult,
    RFDETRDetector,
)
from arachne_extraction.vision.sam_segmenter import (
    SAMSegmenter,
    SegmentationResult,
)

logger = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


# ============================================================================
# Pipeline Configuration
# ============================================================================


class VisionPipelineConfig(BaseModel):
    """Configuration for the full vision pipeline."""

    # SAM 3 settings
    sam_model_path: str | None = None
    sam_model_variant: str = "sam3-base"
    sam_quantized: bool = True

    # RF-DETR settings
    rfdetr_model_path: str | None = None
    rfdetr_model_variant: str = "rfdetr-base"
    rfdetr_confidence_threshold: float = 0.3

    # Crop extraction settings
    crop_model: str = "qwen3-vl"
    crop_ollama_url: str = "http://localhost:11434"
    crop_remote_model: str | None = None
    crop_api_key: str | None = None
    crop_padding: int = 10

    # Assembly settings
    proximity_threshold: int = 50

    # Segmentation prompts
    default_prompt: str = "content blocks"

    # Device
    device: str = "auto"


# ============================================================================
# Pipeline Result
# ============================================================================


@dataclass
class VisionPipelineResult:
    """Complete result from the vision pipeline.

    Includes outputs from each stage for debugging and benchmarking.
    """

    # Final assembled entities
    entities: list[dict[str, Any]] = field(default_factory=list)

    # Structured output (if Pydantic schema was provided)
    structured_data: BaseModel | None = None

    # Per-stage results for transparency
    segmentation: SegmentationResult | None = None
    detection: DetectionResult | None = None
    assembly: AssemblyResult | None = None

    # Metadata
    total_time_ms: int = 0
    segmentation_time_ms: int = 0
    detection_time_ms: int = 0
    extraction_time_ms: int = 0
    assembly_time_ms: int = 0

    # Pipeline stats
    segments_found: int = 0
    elements_detected: int = 0
    content_elements: int = 0
    crops_processed: int = 0
    crops_successful: int = 0

    @property
    def success(self) -> bool:
        return len(self.entities) > 0 or self.structured_data is not None


# ============================================================================
# Vision Pipeline Orchestrator
# ============================================================================


class VisionPipeline:
    """Orchestrates the full SAM 3 → RF-DETR → VLM → Pydantic pipeline.

    This is the "wow factor" — a genuine multi-model CV pipeline that
    processes screenshots into structured data. Each model plays a
    distinct role:

    - SAM 3: WHERE the entities are (segmentation)
    - RF-DETR: WHAT TYPE each segment is (detection + classification)
    - VLM: THE ACTUAL DATA from each segment (OCR + understanding)

    This separation of concerns is textbook ML systems design.

    Usage:
        pipeline = VisionPipeline(config=VisionPipelineConfig(
            crop_ollama_url="http://localhost:11434",
        ))

        result = await pipeline.process(
            image=screenshot_bytes,
            prompt="product cards",
        )

        for entity in result.entities:
            print(entity)

        # Or with Pydantic schema enforcement:
        class Product(BaseModel):
            name: str
            price: float

        result = await pipeline.process(
            image=screenshot_bytes,
            prompt="product cards",
            schema=Product,
        )
        print(result.structured_data)
    """

    def __init__(self, config: VisionPipelineConfig | None = None):
        self.config = config or VisionPipelineConfig()

        self.segmenter = SAMSegmenter(
            model_path=self.config.sam_model_path,
            model_variant=self.config.sam_model_variant,
            device=self.config.device,
            quantized=self.config.sam_quantized,
        )

        self.detector = RFDETRDetector(
            model_path=self.config.rfdetr_model_path,
            model_variant=self.config.rfdetr_model_variant,
            device=self.config.device,
            confidence_threshold=self.config.rfdetr_confidence_threshold,
        )

        self.crop_extractor = CropExtractor(
            model=self.config.crop_model,
            ollama_base_url=self.config.crop_ollama_url,
            remote_model=self.config.crop_remote_model,
            api_key=self.config.crop_api_key,
        )

    async def process(
        self,
        image: bytes,
        prompt: str | None = None,
        *,
        schema: type[T] | None = None,
        url: str = "unknown",
    ) -> VisionPipelineResult:
        """Run the full vision pipeline on a screenshot.

        Args:
            image: Full-page screenshot as PNG bytes.
            prompt: What to look for (e.g., "product cards", "pricing").
            schema: Optional Pydantic schema for structured output.
            url: Source URL for context.

        Returns:
            VisionPipelineResult with entities and per-stage data.
        """
        total_start = time.monotonic()
        prompt = prompt or self.config.default_prompt

        logger.info(
            "vision_pipeline_start",
            prompt=prompt,
            image_bytes=len(image),
            url=url,
        )

        # Stage 1: SAM 3 Segmentation
        seg_start = time.monotonic()
        segmentation = self.segmenter.segment(image, prompt)
        seg_ms = int((time.monotonic() - seg_start) * 1000)

        logger.info(
            "vision_pipeline_segmentation_complete",
            segments=segmentation.mask_count,
            model=segmentation.model_used,
            time_ms=seg_ms,
        )

        # Stage 2: RF-DETR Detection
        det_start = time.monotonic()
        detection = self.detector.detect(image, regions=segmentation.boxes)
        det_ms = int((time.monotonic() - det_start) * 1000)

        content_elements = detection.content_elements

        logger.info(
            "vision_pipeline_detection_complete",
            total_elements=len(detection.elements),
            content_elements=len(content_elements),
            model=detection.model_used,
            time_ms=det_ms,
        )

        # Stage 3: Crop Extraction
        ext_start = time.monotonic()
        crop_results = await self.crop_extractor.extract_crops(
            image, content_elements, padding=self.config.crop_padding,
        )
        ext_ms = int((time.monotonic() - ext_start) * 1000)

        successful_crops = sum(1 for r in crop_results if r.error is None)

        logger.info(
            "vision_pipeline_extraction_complete",
            total_crops=len(crop_results),
            successful=successful_crops,
            time_ms=ext_ms,
        )

        # Stage 4: Assembly
        asm_start = time.monotonic()
        assembly = CropExtractor.assemble_entities(
            crop_results,
            proximity_threshold=self.config.proximity_threshold,
        )
        asm_ms = int((time.monotonic() - asm_start) * 1000)

        # Optional: enforce Pydantic schema on assembled entities
        structured_data = None
        if schema is not None and assembly.entities:
            structured_data = self._enforce_schema(assembly.entities, schema)

        total_ms = int((time.monotonic() - total_start) * 1000)

        logger.info(
            "vision_pipeline_complete",
            entities=len(assembly.entities),
            total_time_ms=total_ms,
            stages=f"seg:{seg_ms}ms det:{det_ms}ms ext:{ext_ms}ms asm:{asm_ms}ms",
        )

        return VisionPipelineResult(
            entities=assembly.entities,
            structured_data=structured_data,
            segmentation=segmentation,
            detection=detection,
            assembly=assembly,
            total_time_ms=total_ms,
            segmentation_time_ms=seg_ms,
            detection_time_ms=det_ms,
            extraction_time_ms=ext_ms,
            assembly_time_ms=asm_ms,
            segments_found=segmentation.mask_count,
            elements_detected=len(detection.elements),
            content_elements=len(content_elements),
            crops_processed=len(crop_results),
            crops_successful=successful_crops,
        )

    def _enforce_schema(
        self,
        entities: list[dict],
        schema: type[T],
    ) -> T | None:
        """Attempt to validate assembled entities against a Pydantic schema.

        Tries to merge entity data into the schema format. This handles
        the common case where entity data has been extracted as separate
        dictionaries that need to be combined.
        """
        # First, try flattening all entities into one dict
        merged: dict = {}
        for entity in entities:
            for key, value in entity.items():
                if isinstance(value, dict):
                    merged.update(value)
                else:
                    merged[key] = value

        try:
            return schema.model_validate(merged)
        except Exception:
            pass

        # Try each entity individually
        for entity in entities:
            try:
                flat = {}
                for value in entity.values():
                    if isinstance(value, dict):
                        flat.update(value)
                return schema.model_validate(flat)
            except Exception:
                continue

        logger.warning(
            "vision_pipeline_schema_enforcement_failed",
            schema=schema.__name__,
            entity_count=len(entities),
        )
        return None
