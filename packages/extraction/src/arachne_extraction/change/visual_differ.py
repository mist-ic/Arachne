"""
Visual differencing using perceptual hashing and SSIM.

Compares screenshots across crawl snapshots to detect visual changes.
Catches changes that DOM diffing misses (CSS-only changes, image swaps,
Canvas/SVG rendering differences).

Methods:
    1. pHash (perceptual hash): Fast binary comparison, good for
       detecting major layout changes.
    2. SSIM (Structural Similarity Index): More nuanced, captures
       local structure and luminance changes.

References:
    - Phase4.md Step 4.3: Visual diffing with pHash/SSIM
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class VisualDiffResult:
    """Result of visual comparison between two screenshots."""

    similarity: float  # 0-1 combined similarity
    phash_distance: int  # Hamming distance between perceptual hashes
    phash_similarity: float  # 0-1 normalized from phash_distance
    ssim_score: float  # -1 to 1 (typically 0-1 for same-type images)
    method: str  # "phash+ssim", "phash_only", "pixel_fallback"
    image_a_size: tuple[int, int] = (0, 0)
    image_b_size: tuple[int, int] = (0, 0)


class VisualDiffer:
    """Compare screenshots using perceptual hashing and SSIM.

    Usage:
        differ = VisualDiffer()
        result = differ.compare(screenshot_old, screenshot_new)

        if result.similarity < 0.8:
            print("Significant visual change detected!")
    """

    def __init__(
        self,
        phash_weight: float = 0.3,
        ssim_weight: float = 0.7,
    ):
        """Initialize visual differ.

        Args:
            phash_weight: Weight for pHash similarity in combined score.
            ssim_weight: Weight for SSIM in combined score.
        """
        self.phash_weight = phash_weight
        self.ssim_weight = ssim_weight

    def compare(
        self,
        image_a: bytes,
        image_b: bytes,
    ) -> VisualDiffResult:
        """Compare two screenshots for visual similarity.

        Args:
            image_a: First (old) screenshot as PNG bytes.
            image_b: Second (new) screenshot as PNG bytes.

        Returns:
            VisualDiffResult with similarity scores.
        """
        try:
            from PIL import Image

            img_a = Image.open(io.BytesIO(image_a)).convert("RGB")
            img_b = Image.open(io.BytesIO(image_b)).convert("RGB")

            size_a = img_a.size
            size_b = img_b.size
        except ImportError:
            logger.warning("visual_differ_no_pillow")
            return VisualDiffResult(
                similarity=0.5,
                phash_distance=0,
                phash_similarity=0.5,
                ssim_score=0.5,
                method="unavailable",
            )

        # pHash comparison
        phash_dist, phash_sim = self._compute_phash(img_a, img_b)

        # SSIM comparison
        ssim_score = self._compute_ssim(img_a, img_b)

        # Combined score
        if ssim_score >= 0:
            similarity = (
                self.phash_weight * phash_sim +
                self.ssim_weight * ssim_score
            )
            method = "phash+ssim"
        else:
            similarity = phash_sim
            method = "phash_only"

        return VisualDiffResult(
            similarity=max(0.0, min(1.0, similarity)),
            phash_distance=phash_dist,
            phash_similarity=phash_sim,
            ssim_score=ssim_score,
            method=method,
            image_a_size=size_a,
            image_b_size=size_b,
        )

    @staticmethod
    def _compute_phash(img_a, img_b) -> tuple[int, float]:
        """Compute perceptual hash distance between two images."""
        try:
            import imagehash

            hash_a = imagehash.phash(img_a)
            hash_b = imagehash.phash(img_b)
            distance = hash_a - hash_b

            # Normalize to 0-1 similarity (64 bits in phash)
            similarity = 1.0 - (distance / 64.0)
            return distance, max(0.0, similarity)

        except ImportError:
            # Fallback: simple average hash
            return VisualDiffer._simple_hash_compare(img_a, img_b)

    @staticmethod
    def _simple_hash_compare(img_a, img_b) -> tuple[int, float]:
        """Simple average hash comparison (pure PIL fallback)."""
        size = (8, 8)

        a_small = img_a.resize(size).convert("L")
        b_small = img_b.resize(size).convert("L")

        a_pixels = list(a_small.getdata())
        b_pixels = list(b_small.getdata())

        a_mean = sum(a_pixels) / len(a_pixels)
        b_mean = sum(b_pixels) / len(b_pixels)

        a_hash = [1 if p > a_mean else 0 for p in a_pixels]
        b_hash = [1 if p > b_mean else 0 for p in b_pixels]

        distance = sum(a != b for a, b in zip(a_hash, b_hash))
        similarity = 1.0 - (distance / len(a_hash))

        return distance, similarity

    @staticmethod
    def _compute_ssim(img_a, img_b) -> float:
        """Compute Structural Similarity Index (SSIM)."""
        try:
            import numpy as np
            from skimage.metrics import structural_similarity

            # Resize to same dimensions for comparison
            target_size = (
                min(img_a.width, img_b.width, 1024),
                min(img_a.height, img_b.height, 768),
            )

            a_resized = img_a.resize(target_size)
            b_resized = img_b.resize(target_size)

            a_array = np.array(a_resized)
            b_array = np.array(b_resized)

            # Compute SSIM
            ssim = structural_similarity(
                a_array, b_array,
                channel_axis=2,  # Color channel axis
                win_size=min(7, min(target_size)),  # Window size
            )

            return float(ssim)

        except ImportError:
            logger.debug("ssim_not_available", reason="scikit-image not installed")
            return -1.0  # Indicates SSIM unavailable
        except Exception as e:
            logger.warning("ssim_computation_failed", error=str(e))
            return -1.0
