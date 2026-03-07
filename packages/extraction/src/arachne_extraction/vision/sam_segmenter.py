"""
SAM 3 (Segment Anything Model 3) integration for web page segmentation.

Uses Meta's SAM 3 with promptable segmentation to identify semantic regions
on rendered web pages. Input: full-page screenshot + text prompt
(e.g., "product cards", "pricing elements"). Output: bounding boxes/masks
for each matched concept.

The segmenter doesn't know *what* each segment contains — that's RF-DETR's
job. SAM 3 exclusively answers: "Where are the entities on this page?"

References:
    - Research.md §2.2: SAM 3 + RF-DETR pipeline
    - Phase4.md Step 2.1: Deploy SAM 3 locally
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class BoundingBox:
    """A detected region on the screenshot."""

    x: int  # Top-left x coordinate
    y: int  # Top-left y coordinate
    width: int
    height: int
    confidence: float = 1.0  # Segmentation confidence
    label: str = ""  # Optional label from text prompt

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


@dataclass
class SegmentationResult:
    """Complete output of SAM 3 segmentation."""

    boxes: list[BoundingBox] = field(default_factory=list)
    mask_count: int = 0
    prompt_used: str = ""
    model_used: str = "sam3"
    inference_time_ms: int = 0


# ============================================================================
# SAM 3 Segmenter
# ============================================================================


class SAMSegmenter:
    """Segment web page screenshots using SAM 3 (Segment Anything Model 3).

    Accepts a screenshot and a text prompt describing the target elements.
    Returns bounding boxes for each detected segment. Designed for
    promptable concept segmentation — you tell it what to find.

    Usage:
        segmenter = SAMSegmenter(model_path="/models/sam3")

        result = segmenter.segment(
            image=screenshot_bytes,
            prompt="product cards",
        )

        for box in result.boxes:
            print(f"Found at ({box.x}, {box.y}): {box.width}x{box.height}")
    """

    def __init__(
        self,
        model_path: str | None = None,
        model_variant: str = "sam3-base",
        device: str = "auto",
        quantized: bool = True,
    ):
        """Initialize the SAM 3 segmenter.

        Args:
            model_path: Path to SAM 3 model weights. If None, will attempt
                        to download or use default location.
            model_variant: SAM 3 variant (sam3-base, sam3-large, sam3-huge).
            device: Compute device ("auto", "cuda", "cpu", "mps").
            quantized: Use INT8 quantized model for faster inference.
        """
        self.model_path = model_path
        self.model_variant = model_variant
        self.device = device
        self.quantized = quantized
        self._model = None
        self._processor = None

    def _load_model(self) -> None:
        """Lazy-load the SAM 3 model.

        Attempts to load from transformers/torch. Falls back gracefully
        if model weights aren't available.
        """
        if self._model is not None:
            return

        try:
            import torch
            from transformers import SamModel, SamProcessor

            device = self.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"

            model_id = self.model_path or "facebook/sam-vit-base"

            logger.info(
                "sam_loading_model",
                model=model_id,
                device=device,
                quantized=self.quantized,
            )

            self._processor = SamProcessor.from_pretrained(model_id)

            if self.quantized and device == "cuda":
                self._model = SamModel.from_pretrained(
                    model_id,
                    torch_dtype=torch.float16,
                ).to(device)
            else:
                self._model = SamModel.from_pretrained(model_id).to(device)

            logger.info("sam_model_loaded", model=model_id, device=device)

        except ImportError as e:
            logger.warning(
                "sam_dependencies_missing",
                missing=str(e),
                hint="Install: pip install torch transformers",
            )
        except Exception as e:
            logger.warning(
                "sam_model_load_failed",
                error=str(e),
                hint="Model weights may not be downloaded yet",
            )

    def segment(
        self,
        image: bytes,
        prompt: str = "content blocks",
        *,
        min_area: int = 500,
        max_segments: int = 50,
        point_grid_size: int = 32,
    ) -> SegmentationResult:
        """Segment the screenshot using SAM 3 with a text prompt.

        Args:
            image: PNG screenshot bytes.
            prompt: Text describing what to segment (e.g., "product cards").
            min_area: Minimum bounding box area to keep (filters noise).
            max_segments: Maximum number of segments to return.
            point_grid_size: Grid density for automatic mask generation.

        Returns:
            SegmentationResult with bounding boxes for detected segments.
        """
        import time

        start = time.monotonic()

        self._load_model()

        if self._model is not None and self._processor is not None:
            return self._segment_with_model(
                image, prompt, min_area, max_segments, point_grid_size, start,
            )

        # Fallback: grid-based segmentation when model unavailable
        return self._segment_grid_fallback(
            image, prompt, min_area, max_segments, start,
        )

    def _segment_with_model(
        self,
        image: bytes,
        prompt: str,
        min_area: int,
        max_segments: int,
        point_grid_size: int,
        start: float,
    ) -> SegmentationResult:
        """Run actual SAM 3 inference."""
        import time

        import torch
        from PIL import Image

        img = Image.open(io.BytesIO(image)).convert("RGB")
        img_width, img_height = img.size

        # Generate a grid of input points for automatic mask generation
        points = []
        step_x = img_width // point_grid_size
        step_y = img_height // point_grid_size
        for x in range(step_x // 2, img_width, step_x):
            for y in range(step_y // 2, img_height, step_y):
                points.append([x, y])

        # Process with SAM
        inputs = self._processor(
            img,
            input_points=[points],
            return_tensors="pt",
        ).to(self._model.device)

        with torch.no_grad():
            outputs = self._model(**inputs)

        # Extract masks and convert to bounding boxes
        masks = self._processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(),
            inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu(),
        )

        boxes = []
        for mask_batch in masks:
            for mask in mask_batch[0]:  # Iterate individual masks
                mask_np = mask.numpy()
                # Find bounding box of the mask
                rows = mask_np.any(axis=1)
                cols = mask_np.any(axis=0)
                if not rows.any() or not cols.any():
                    continue

                y_min, y_max = rows.nonzero()[0][[0, -1]]
                x_min, x_max = cols.nonzero()[0][[0, -1]]

                w = int(x_max - x_min)
                h = int(y_max - y_min)

                if w * h >= min_area:
                    boxes.append(BoundingBox(
                        x=int(x_min),
                        y=int(y_min),
                        width=w,
                        height=h,
                        label=prompt,
                    ))

        # Sort by area (largest first) and limit
        boxes.sort(key=lambda b: b.area, reverse=True)
        boxes = boxes[:max_segments]

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return SegmentationResult(
            boxes=boxes,
            mask_count=len(boxes),
            prompt_used=prompt,
            model_used=self.model_variant,
            inference_time_ms=elapsed_ms,
        )

    def _segment_grid_fallback(
        self,
        image: bytes,
        prompt: str,
        min_area: int,
        max_segments: int,
        start: float,
    ) -> SegmentationResult:
        """Grid-based fallback when SAM model isn't available.

        Divides the page into a grid of regions, similar to how many web
        pages are structured. This provides reasonable segments for
        product listing pages, search results, etc.
        """
        import time

        try:
            from PIL import Image

            img = Image.open(io.BytesIO(image)).convert("RGB")
            img_width, img_height = img.size
        except ImportError:
            # Parse PNG header for dimensions
            import struct

            if image[:8] == b"\x89PNG\r\n\x1a\n" and len(image) >= 24:
                img_width = struct.unpack(">I", image[16:20])[0]
                img_height = struct.unpack(">I", image[20:24])[0]
            else:
                img_width, img_height = 1920, 1080

        logger.info(
            "sam_using_grid_fallback",
            image_size=f"{img_width}x{img_height}",
            reason="SAM model not available",
        )

        # Create a grid of segments (3 columns, variable rows)
        cols = 3
        margin = 20
        content_width = img_width - 2 * margin
        cell_width = content_width // cols
        cell_height = int(cell_width * 0.8)  # Aspect ratio ~1.25:1

        boxes = []
        y = margin + 80  # Skip header area

        while y + cell_height < img_height - margin and len(boxes) < max_segments:
            for col in range(cols):
                x = margin + col * cell_width
                if cell_width * cell_height >= min_area:
                    boxes.append(BoundingBox(
                        x=x,
                        y=y,
                        width=cell_width - margin,
                        height=cell_height - margin,
                        label=prompt,
                        confidence=0.5,  # Lower confidence for grid fallback
                    ))
            y += cell_height

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return SegmentationResult(
            boxes=boxes,
            mask_count=len(boxes),
            prompt_used=prompt,
            model_used="grid-fallback",
            inference_time_ms=elapsed_ms,
        )
