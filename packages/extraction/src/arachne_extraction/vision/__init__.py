"""
Vision extraction subpackage — CV pipeline for web data extraction.

Provides multi-model computer vision pipelines that process page screenshots
into structured data. Includes SAM 3 segmentation, RF-DETR detection,
cropped segment extraction, and a full pipeline orchestrator.

Modules:
    sam_segmenter    — SAM 3 promptable concept segmentation
    rfdetr_detector  — RF-DETR real-time UI element detection
    crop_extractor   — Cropped segment → VLM text extraction
    pipeline         — Full SAM → RF-DETR → VLM → Pydantic pipeline
"""

from arachne_extraction.vision.pipeline import VisionPipeline
from arachne_extraction.vision.sam_segmenter import SAMSegmenter
from arachne_extraction.vision.rfdetr_detector import RFDETRDetector
from arachne_extraction.vision.crop_extractor import CropExtractor

__all__ = [
    "VisionPipeline",
    "SAMSegmenter",
    "RFDETRDetector",
    "CropExtractor",
]
