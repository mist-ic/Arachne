"""
Embedding-based semantic similarity for change detection.

Computes cosine similarity between text embeddings of page content
across crawl snapshots. Detects when page *meaning* has changed,
even if the DOM structure looks the same (e.g., products replaced
with different products on a category page).

References:
    - Phase4.md Step 4.2: Embedding similarity
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class EmbeddingSimilarityResult:
    """Result of semantic similarity comparison."""

    similarity: float  # 0-1 cosine similarity
    method: str  # "embedding", "tfidf", "jaccard"
    segments_compared: int = 0
    content_hash_a: str = ""
    content_hash_b: str = ""


class EmbeddingSimilarity:
    """Compute semantic similarity between two text contents.

    Supports three backends (in order of preference):
    1. Sentence-transformers (best quality)
    2. TF-IDF cosine similarity (no GPU needed)
    3. Jaccard similarity on word n-grams (pure Python fallback)

    Usage:
        sim = EmbeddingSimilarity()
        result = sim.compare(old_text, new_text)
        print(f"Similarity: {result.similarity:.2f}")
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        self.model_name = model
        self._model = None

    def compare(self, text_a: str, text_b: str) -> EmbeddingSimilarityResult:
        """Compare two texts for semantic similarity.

        Args:
            text_a: First (old) text content.
            text_b: Second (new) text content.

        Returns:
            EmbeddingSimilarityResult with similarity score.
        """
        hash_a = hashlib.sha256(text_a.encode()).hexdigest()[:16]
        hash_b = hashlib.sha256(text_b.encode()).hexdigest()[:16]

        # Identical content
        if hash_a == hash_b:
            return EmbeddingSimilarityResult(
                similarity=1.0,
                method="hash_match",
                content_hash_a=hash_a,
                content_hash_b=hash_b,
            )

        # Try sentence-transformers
        try:
            return self._compare_embeddings(text_a, text_b, hash_a, hash_b)
        except ImportError:
            pass

        # Try TF-IDF
        try:
            return self._compare_tfidf(text_a, text_b, hash_a, hash_b)
        except ImportError:
            pass

        # Fallback: Jaccard on word n-grams
        return self._compare_jaccard(text_a, text_b, hash_a, hash_b)

    def _compare_embeddings(
        self, text_a: str, text_b: str,
        hash_a: str, hash_b: str,
    ) -> EmbeddingSimilarityResult:
        """Compare using sentence-transformer embeddings."""
        from sentence_transformers import SentenceTransformer
        import numpy as np

        if self._model is None:
            self._model = SentenceTransformer(self.model_name)

        # Chunk texts into segments for better comparison
        segments_a = self._chunk_text(text_a)
        segments_b = self._chunk_text(text_b)

        emb_a = self._model.encode(segments_a)
        emb_b = self._model.encode(segments_b)

        # Average embedding similarity
        mean_a = np.mean(emb_a, axis=0)
        mean_b = np.mean(emb_b, axis=0)

        similarity = float(np.dot(mean_a, mean_b) / (
            np.linalg.norm(mean_a) * np.linalg.norm(mean_b) + 1e-10
        ))

        return EmbeddingSimilarityResult(
            similarity=max(0.0, min(1.0, similarity)),
            method="embedding",
            segments_compared=len(segments_a) + len(segments_b),
            content_hash_a=hash_a,
            content_hash_b=hash_b,
        )

    def _compare_tfidf(
        self, text_a: str, text_b: str,
        hash_a: str, hash_b: str,
    ) -> EmbeddingSimilarityResult:
        """Compare using TF-IDF cosine similarity."""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vectorizer = TfidfVectorizer(max_features=5000, stop_words="english")
        tfidf_matrix = vectorizer.fit_transform([text_a, text_b])
        similarity = float(cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0, 0])

        return EmbeddingSimilarityResult(
            similarity=max(0.0, min(1.0, similarity)),
            method="tfidf",
            content_hash_a=hash_a,
            content_hash_b=hash_b,
        )

    def _compare_jaccard(
        self, text_a: str, text_b: str,
        hash_a: str, hash_b: str,
    ) -> EmbeddingSimilarityResult:
        """Fallback: n-gram Jaccard similarity (pure Python)."""
        n = 3  # Character trigrams for robustness

        grams_a = {text_a[i:i + n].lower() for i in range(len(text_a) - n + 1)}
        grams_b = {text_b[i:i + n].lower() for i in range(len(text_b) - n + 1)}

        if not grams_a and not grams_b:
            return EmbeddingSimilarityResult(
                similarity=1.0, method="jaccard",
                content_hash_a=hash_a, content_hash_b=hash_b,
            )

        intersection = len(grams_a & grams_b)
        union = len(grams_a | grams_b)

        similarity = intersection / union if union > 0 else 0.0

        return EmbeddingSimilarityResult(
            similarity=similarity,
            method="jaccard",
            content_hash_a=hash_a,
            content_hash_b=hash_b,
        )

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 200) -> list[str]:
        """Split text into chunks for embedding."""
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i + chunk_size])
            if chunk.strip():
                chunks.append(chunk)
        return chunks if chunks else [text[:1000]]
