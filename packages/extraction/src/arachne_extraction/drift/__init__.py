"""
Drift detection subpackage — monitors and adapts to site changes.

Detects when target sites change their layout (breaking extraction schemas)
and auto-repairs schemas via LLM without human intervention.

Modules:
    detector  — Multi-signal drift detection
    repairer  — LLM-powered schema auto-repair
    history   — Schema version tracking with rollback
"""

from arachne_extraction.drift.detector import DriftDetector
from arachne_extraction.drift.repairer import SchemaRepairer
from arachne_extraction.drift.history import SchemaHistory

__all__ = [
    "DriftDetector",
    "SchemaRepairer",
    "SchemaHistory",
]
