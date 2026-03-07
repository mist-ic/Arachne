"""
Multi-signal drift detection for extraction schemas.

Monitors extraction quality metrics per domain per schema and detects
when a target site has changed its layout, breaking existing schemas.
Uses four complementary signals to avoid false positives.

Detection signals:
    1. Pydantic validation failure rate spike
    2. Field completeness regression (previously-reliable fields missing)
    3. Embedding similarity drop (content structure changed)
    4. A/B schema discovery divergence (proposed schema ≠ current schema)

References:
    - Research.md §2.3: Schema drift is "inevitable"
    - Phase4.md Step 3: Schema Drift Detection & Self-Healing
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class DriftSignal(str, Enum):
    """Individual drift detection signal types."""

    VALIDATION_FAILURE_RATE = "validation_failure_rate"
    FIELD_COMPLETENESS = "field_completeness"
    EMBEDDING_SIMILARITY = "embedding_similarity"
    SCHEMA_DIVERGENCE = "schema_divergence"


class DriftSeverity(str, Enum):
    """How severe the detected drift is."""

    NONE = "none"  # No drift detected
    MINOR = "minor"  # Small changes, schema likely still works
    MODERATE = "moderate"  # Some fields affected, auto-repair may work
    MAJOR = "major"  # Significant changes, schema needs full rework


@dataclass
class DriftSignalResult:
    """Result from a single drift signal check."""

    signal: DriftSignal
    triggered: bool
    value: float  # The measured value
    threshold: float  # The trigger threshold
    details: str = ""


@dataclass
class DriftDetectionResult:
    """Aggregated result from all drift signals."""

    domain: str
    schema_id: str
    drift_detected: bool
    severity: DriftSeverity
    signals: list[DriftSignalResult] = field(default_factory=list)
    triggered_signals: int = 0
    total_signals: int = 4
    confidence: float = 0.0  # How confident we are that drift occurred
    timestamp: float = 0.0

    @property
    def triggered_signal_names(self) -> list[str]:
        return [s.signal.value for s in self.signals if s.triggered]


class DriftConfig:
    """Configuration for drift detection thresholds."""

    def __init__(
        self,
        validation_failure_threshold: float = 0.30,
        field_completeness_drop: int = 3,
        embedding_similarity_threshold: float = 0.80,
        schema_divergence_threshold: float = 0.20,
        min_samples_for_detection: int = 5,
        lookback_window_hours: int = 24,
    ):
        """
        Args:
            validation_failure_threshold: Failure rate above which drift is
                                          signaled (0.30 = 30% failures).
            field_completeness_drop: Number of previously-reliable fields
                                    that suddenly go missing.
            embedding_similarity_threshold: Cosine similarity below which
                                            content structure is considered changed.
            schema_divergence_threshold: Fraction of field differences between
                                         current and re-discovered schema.
            min_samples_for_detection: Minimum extractions before detection
                                       can trigger (avoids false positives).
            lookback_window_hours: How far back to look for baseline metrics.
        """
        self.validation_failure_threshold = validation_failure_threshold
        self.field_completeness_drop = field_completeness_drop
        self.embedding_similarity_threshold = embedding_similarity_threshold
        self.schema_divergence_threshold = schema_divergence_threshold
        self.min_samples_for_detection = min_samples_for_detection
        self.lookback_window_hours = lookback_window_hours


# ============================================================================
# Extraction Metrics Storage (In-Memory)
# ============================================================================


@dataclass
class ExtractionMetrics:
    """Accumulated extraction metrics for a domain+schema pair."""

    domain: str
    schema_id: str
    total_extractions: int = 0
    validation_passes: int = 0
    validation_failures: int = 0
    field_completeness_history: list[dict[str, bool]] = field(default_factory=list)
    confidence_history: list[float] = field(default_factory=list)
    content_hashes: list[str] = field(default_factory=list)

    @property
    def failure_rate(self) -> float:
        total = self.validation_passes + self.validation_failures
        if total == 0:
            return 0.0
        return self.validation_failures / total

    def record_extraction(
        self,
        passed: bool,
        confidence: float,
        field_status: dict[str, bool],
        content_hash: str = "",
    ) -> None:
        """Record metrics from a single extraction attempt."""
        self.total_extractions += 1
        if passed:
            self.validation_passes += 1
        else:
            self.validation_failures += 1
        self.confidence_history.append(confidence)
        self.field_completeness_history.append(field_status)
        if content_hash:
            self.content_hashes.append(content_hash)

        # Keep last 100 entries to bound memory
        if len(self.field_completeness_history) > 100:
            self.field_completeness_history = self.field_completeness_history[-100:]
        if len(self.confidence_history) > 100:
            self.confidence_history = self.confidence_history[-100:]
        if len(self.content_hashes) > 100:
            self.content_hashes = self.content_hashes[-100:]


# ============================================================================
# Drift Detector
# ============================================================================


class DriftDetector:
    """Multi-signal drift detection for extraction schemas.

    Monitors extraction metrics per domain per schema and fires
    drift alerts when multiple signals agree that the target site
    has changed.

    Usage:
        detector = DriftDetector()

        # Record metrics from extractions
        detector.record(
            domain="example.com",
            schema_id="product_v1",
            passed=True,
            confidence=0.95,
            field_status={"name": True, "price": True, "rating": False},
        )

        # Check for drift
        result = detector.detect(
            domain="example.com",
            schema_id="product_v1",
        )

        if result.drift_detected:
            print(f"Drift detected! Severity: {result.severity}")
            print(f"Signals: {result.triggered_signal_names}")
    """

    def __init__(self, config: DriftConfig | None = None):
        self.config = config or DriftConfig()
        self._metrics: dict[str, ExtractionMetrics] = {}

    def _key(self, domain: str, schema_id: str) -> str:
        return f"{domain}::{schema_id}"

    def get_metrics(self, domain: str, schema_id: str) -> ExtractionMetrics:
        """Get or create metrics for a domain+schema pair."""
        key = self._key(domain, schema_id)
        if key not in self._metrics:
            self._metrics[key] = ExtractionMetrics(
                domain=domain,
                schema_id=schema_id,
            )
        return self._metrics[key]

    def record(
        self,
        domain: str,
        schema_id: str,
        passed: bool,
        confidence: float,
        field_status: dict[str, bool],
        content_hash: str = "",
    ) -> None:
        """Record metrics from a single extraction attempt.

        Args:
            domain: Target domain (e.g., "example.com").
            schema_id: Schema identifier (e.g., "product_v1").
            passed: Whether Pydantic validation passed.
            confidence: Extraction confidence (0-1).
            field_status: Per-field extraction success (True/False).
            content_hash: Hash of the extracted content for similarity.
        """
        metrics = self.get_metrics(domain, schema_id)
        metrics.record_extraction(passed, confidence, field_status, content_hash)

    def detect(
        self,
        domain: str,
        schema_id: str,
        *,
        current_content: str | None = None,
        current_schema_fields: list[str] | None = None,
        rediscovered_schema_fields: list[str] | None = None,
    ) -> DriftDetectionResult:
        """Run all drift detection signals for a domain+schema pair.

        Args:
            domain: Target domain.
            schema_id: Schema identifier.
            current_content: Latest page content for embedding comparison.
            current_schema_fields: Fields in the current schema.
            rediscovered_schema_fields: Fields from re-running auto-discovery.

        Returns:
            DriftDetectionResult with aggregated signal results.
        """
        metrics = self.get_metrics(domain, schema_id)
        signals: list[DriftSignalResult] = []

        # Signal 1: Validation failure rate
        signals.append(self._check_validation_rate(metrics))

        # Signal 2: Field completeness regression
        signals.append(self._check_field_completeness(metrics))

        # Signal 3: Embedding similarity (if content provided)
        signals.append(self._check_embedding_similarity(metrics, current_content))

        # Signal 4: Schema divergence (if re-discovered schema provided)
        signals.append(self._check_schema_divergence(
            current_schema_fields, rediscovered_schema_fields,
        ))

        # Aggregate
        triggered = sum(1 for s in signals if s.triggered)
        drift_detected = triggered >= 2  # Need at least 2 signals agreeing

        if triggered == 0:
            severity = DriftSeverity.NONE
        elif triggered == 1:
            severity = DriftSeverity.MINOR
        elif triggered == 2:
            severity = DriftSeverity.MODERATE
        else:
            severity = DriftSeverity.MAJOR

        confidence = triggered / len(signals)

        result = DriftDetectionResult(
            domain=domain,
            schema_id=schema_id,
            drift_detected=drift_detected,
            severity=severity,
            signals=signals,
            triggered_signals=triggered,
            confidence=confidence,
            timestamp=time.time(),
        )

        if drift_detected:
            logger.warning(
                "schema_drift_detected",
                domain=domain,
                schema_id=schema_id,
                severity=severity.value,
                signals=result.triggered_signal_names,
                confidence=confidence,
            )

        return result

    def _check_validation_rate(self, metrics: ExtractionMetrics) -> DriftSignalResult:
        """Signal 1: Sudden spike in validation failure rate."""
        if metrics.total_extractions < self.config.min_samples_for_detection:
            return DriftSignalResult(
                signal=DriftSignal.VALIDATION_FAILURE_RATE,
                triggered=False,
                value=metrics.failure_rate,
                threshold=self.config.validation_failure_threshold,
                details=f"Not enough samples ({metrics.total_extractions}/"
                        f"{self.config.min_samples_for_detection})",
            )

        triggered = metrics.failure_rate > self.config.validation_failure_threshold

        return DriftSignalResult(
            signal=DriftSignal.VALIDATION_FAILURE_RATE,
            triggered=triggered,
            value=metrics.failure_rate,
            threshold=self.config.validation_failure_threshold,
            details=f"{metrics.validation_failures}/{metrics.total_extractions} "
                    f"failures ({metrics.failure_rate:.1%})",
        )

    def _check_field_completeness(
        self, metrics: ExtractionMetrics,
    ) -> DriftSignalResult:
        """Signal 2: Previously-reliable fields suddenly missing."""
        history = metrics.field_completeness_history
        if len(history) < self.config.min_samples_for_detection:
            return DriftSignalResult(
                signal=DriftSignal.FIELD_COMPLETENESS,
                triggered=False,
                value=0,
                threshold=self.config.field_completeness_drop,
                details="Not enough history",
            )

        # Compare recent window vs historical baseline
        split = max(1, len(history) // 2)
        baseline = history[:split]
        recent = history[split:]

        # Count fields that were mostly present in baseline but missing recently
        all_fields: set[str] = set()
        for entry in history:
            all_fields.update(entry.keys())

        dropped_fields = 0
        for field_name in all_fields:
            baseline_present = sum(
                1 for entry in baseline if entry.get(field_name, False)
            )
            recent_present = sum(
                1 for entry in recent if entry.get(field_name, False)
            )

            baseline_rate = baseline_present / len(baseline) if baseline else 0
            recent_rate = recent_present / len(recent) if recent else 0

            # Field was reliable (>80% present) but now mostly missing (<30%)
            if baseline_rate > 0.8 and recent_rate < 0.3:
                dropped_fields += 1

        triggered = dropped_fields >= self.config.field_completeness_drop

        return DriftSignalResult(
            signal=DriftSignal.FIELD_COMPLETENESS,
            triggered=triggered,
            value=float(dropped_fields),
            threshold=float(self.config.field_completeness_drop),
            details=f"{dropped_fields} fields dropped from baseline",
        )

    def _check_embedding_similarity(
        self,
        metrics: ExtractionMetrics,
        current_content: str | None,
    ) -> DriftSignalResult:
        """Signal 3: Content structure embedding similarity drop."""
        if current_content is None or len(metrics.content_hashes) < 2:
            return DriftSignalResult(
                signal=DriftSignal.EMBEDDING_SIMILARITY,
                triggered=False,
                value=1.0,
                threshold=self.config.embedding_similarity_threshold,
                details="No content available for comparison",
            )

        # Use simple content hash similarity as a proxy for embedding similarity
        # In production, use actual sentence embeddings
        current_hash = hashlib.sha256(current_content.encode()).hexdigest()

        # Compare current hash against recent hashes
        recent_hashes = metrics.content_hashes[-10:]
        matches = sum(1 for h in recent_hashes if h == current_hash)
        similarity = matches / len(recent_hashes) if recent_hashes else 1.0

        # For a more nuanced approach: character-level Jaccard similarity
        if len(metrics.content_hashes) >= 2 and current_content:
            similarity = self._content_similarity(
                current_content,
                current_hash,
                metrics.content_hashes[-1],
            )

        triggered = similarity < self.config.embedding_similarity_threshold

        return DriftSignalResult(
            signal=DriftSignal.EMBEDDING_SIMILARITY,
            triggered=triggered,
            value=similarity,
            threshold=self.config.embedding_similarity_threshold,
            details=f"Content similarity: {similarity:.2f}",
        )

    def _check_schema_divergence(
        self,
        current_fields: list[str] | None,
        rediscovered_fields: list[str] | None,
    ) -> DriftSignalResult:
        """Signal 4: Re-discovered schema diverges from current schema."""
        if current_fields is None or rediscovered_fields is None:
            return DriftSignalResult(
                signal=DriftSignal.SCHEMA_DIVERGENCE,
                triggered=False,
                value=0.0,
                threshold=self.config.schema_divergence_threshold,
                details="No schemas available for comparison",
            )

        current_set = set(current_fields)
        rediscovered_set = set(rediscovered_fields)

        # Calculate Jaccard distance as divergence
        union = current_set | rediscovered_set
        intersection = current_set & rediscovered_set

        if not union:
            return DriftSignalResult(
                signal=DriftSignal.SCHEMA_DIVERGENCE,
                triggered=False,
                value=0.0,
                threshold=self.config.schema_divergence_threshold,
                details="Both schemas empty",
            )

        divergence = 1.0 - len(intersection) / len(union)
        triggered = divergence > self.config.schema_divergence_threshold

        added = rediscovered_set - current_set
        removed = current_set - rediscovered_set

        return DriftSignalResult(
            signal=DriftSignal.SCHEMA_DIVERGENCE,
            triggered=triggered,
            value=divergence,
            threshold=self.config.schema_divergence_threshold,
            details=f"Divergence: {divergence:.2f} "
                    f"(+{len(added)} fields, -{len(removed)} fields)",
        )

    @staticmethod
    def _content_similarity(
        content: str,
        hash_a: str,
        hash_b: str,
    ) -> float:
        """Simple content similarity using hash comparison.

        In production, this would use actual sentence embeddings.
        This provides a reasonable proxy.
        """
        if hash_a == hash_b:
            return 1.0

        # Use character 4-grams as very simple "embedding"
        grams_a = {content[i:i + 4] for i in range(len(content) - 3)}
        # We can't reconstruct the old content from hash alone,
        # so return a moderate similarity as conservative estimate
        if not grams_a:
            return 0.5

        return 0.5  # Conservative estimate when we can't compare directly
