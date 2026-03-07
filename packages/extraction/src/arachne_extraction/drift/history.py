"""
Schema version history with rollback capability.

Tracks schema evolution over time — each version with timestamps,
the trigger event (manual, auto-repaired, initial), and the schema
definition. Supports diffing between versions and rolling back
if an auto-repaired schema regresses.

References:
    - Phase4.md Step 3.3: Schema version history
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ============================================================================
# Data Models
# ============================================================================


class SchemaChangeType(str, Enum):
    """What triggered a schema change."""

    INITIAL = "initial"
    MANUAL = "manual"
    AUTO_REPAIRED = "auto_repaired"
    ROLLBACK = "rollback"


@dataclass
class SchemaVersion:
    """A single version of an extraction schema."""

    version: int
    domain: str
    schema_id: str
    schema_data: dict[str, str]  # field_name → type
    change_type: SchemaChangeType
    timestamp: float
    change_reason: str = ""
    confidence: float = 0.0
    hash: str = ""

    def __post_init__(self):
        if not self.hash:
            self.hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute a content hash for the schema."""
        content = json.dumps(self.schema_data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class SchemaDiff:
    """Difference between two schema versions."""

    from_version: int
    to_version: int
    added_fields: list[str]
    removed_fields: list[str]
    modified_fields: list[tuple[str, str, str]]  # (field, old_type, new_type)
    unchanged_fields: list[str]

    @property
    def has_changes(self) -> bool:
        return bool(self.added_fields or self.removed_fields or self.modified_fields)

    @property
    def summary(self) -> str:
        parts = []
        if self.added_fields:
            parts.append(f"+{len(self.added_fields)} fields")
        if self.removed_fields:
            parts.append(f"-{len(self.removed_fields)} fields")
        if self.modified_fields:
            parts.append(f"~{len(self.modified_fields)} modified")
        return ", ".join(parts) if parts else "no changes"


# ============================================================================
# Schema History
# ============================================================================


class SchemaHistory:
    """Track schema evolution with version history and rollback.

    Stores schema versions in-memory (in production, backed by PostgreSQL).
    Each version includes the full schema, why it changed, and timestamps.

    Usage:
        history = SchemaHistory()

        # Register initial schema
        history.add_version(
            domain="example.com",
            schema_id="product",
            schema_data={"name": "str", "price": "float"},
            change_type=SchemaChangeType.INITIAL,
        )

        # Auto-repair adds a new version
        history.add_version(
            domain="example.com",
            schema_id="product",
            schema_data={"title": "str", "price": "float", "sku": "str"},
            change_type=SchemaChangeType.AUTO_REPAIRED,
            change_reason="Site redesign detected: name → title, new sku field",
        )

        # Compare versions
        diff = history.diff("example.com", "product", 1, 2)
        print(diff.summary)  # "+1 fields, -0 fields, ~1 modified"

        # Rollback if needed
        history.rollback("example.com", "product", target_version=1)
    """

    def __init__(self):
        self._versions: dict[str, list[SchemaVersion]] = {}

    def _key(self, domain: str, schema_id: str) -> str:
        return f"{domain}::{schema_id}"

    def add_version(
        self,
        domain: str,
        schema_id: str,
        schema_data: dict[str, str],
        change_type: SchemaChangeType,
        change_reason: str = "",
        confidence: float = 0.0,
    ) -> SchemaVersion:
        """Add a new schema version.

        Returns the created SchemaVersion.
        """
        key = self._key(domain, schema_id)
        versions = self._versions.setdefault(key, [])

        version_num = len(versions) + 1

        sv = SchemaVersion(
            version=version_num,
            domain=domain,
            schema_id=schema_id,
            schema_data=schema_data,
            change_type=change_type,
            timestamp=time.time(),
            change_reason=change_reason,
            confidence=confidence,
        )

        versions.append(sv)

        logger.info(
            "schema_version_added",
            domain=domain,
            schema_id=schema_id,
            version=version_num,
            change_type=change_type.value,
            fields=list(schema_data.keys()),
        )

        return sv

    def get_current(self, domain: str, schema_id: str) -> SchemaVersion | None:
        """Get the latest schema version."""
        key = self._key(domain, schema_id)
        versions = self._versions.get(key, [])
        return versions[-1] if versions else None

    def get_version(
        self, domain: str, schema_id: str, version: int,
    ) -> SchemaVersion | None:
        """Get a specific schema version."""
        key = self._key(domain, schema_id)
        versions = self._versions.get(key, [])

        for sv in versions:
            if sv.version == version:
                return sv
        return None

    def get_all_versions(
        self, domain: str, schema_id: str,
    ) -> list[SchemaVersion]:
        """Get all versions for a domain+schema pair."""
        key = self._key(domain, schema_id)
        return self._versions.get(key, [])

    def diff(
        self,
        domain: str,
        schema_id: str,
        from_version: int,
        to_version: int,
    ) -> SchemaDiff | None:
        """Compute the diff between two schema versions."""
        v_from = self.get_version(domain, schema_id, from_version)
        v_to = self.get_version(domain, schema_id, to_version)

        if v_from is None or v_to is None:
            return None

        old_fields = set(v_from.schema_data.keys())
        new_fields = set(v_to.schema_data.keys())

        added = list(new_fields - old_fields)
        removed = list(old_fields - new_fields)

        modified = []
        unchanged = []
        for f in old_fields & new_fields:
            old_type = v_from.schema_data[f]
            new_type = v_to.schema_data[f]
            if old_type != new_type:
                modified.append((f, old_type, new_type))
            else:
                unchanged.append(f)

        return SchemaDiff(
            from_version=from_version,
            to_version=to_version,
            added_fields=added,
            removed_fields=removed,
            modified_fields=modified,
            unchanged_fields=unchanged,
        )

    def rollback(
        self,
        domain: str,
        schema_id: str,
        target_version: int,
    ) -> SchemaVersion | None:
        """Rollback to a previous schema version.

        Creates a new version entry (type=ROLLBACK) with the old schema
        data, preserving the full timeline.

        Returns the new version if successful, None if target not found.
        """
        target = self.get_version(domain, schema_id, target_version)
        if target is None:
            logger.error(
                "schema_rollback_failed",
                domain=domain,
                schema_id=schema_id,
                target_version=target_version,
                reason="version not found",
            )
            return None

        new_version = self.add_version(
            domain=domain,
            schema_id=schema_id,
            schema_data=target.schema_data,
            change_type=SchemaChangeType.ROLLBACK,
            change_reason=f"Rolled back to version {target_version}",
        )

        logger.info(
            "schema_rollback_complete",
            domain=domain,
            schema_id=schema_id,
            from_version=new_version.version - 1,
            to_version=new_version.version,
            rollback_target=target_version,
        )

        return new_version

    def format_timeline(self, domain: str, schema_id: str) -> str:
        """Format the version history as a readable timeline."""
        versions = self.get_all_versions(domain, schema_id)
        if not versions:
            return f"No history for {domain}::{schema_id}"

        lines = [f"Schema History: {domain}::{schema_id}", ""]

        for sv in versions:
            timestamp = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(sv.timestamp),
            )
            lines.append(
                f"  v{sv.version} [{sv.change_type.value}] {timestamp}"
            )
            lines.append(f"    Fields: {', '.join(sv.schema_data.keys())}")
            if sv.change_reason:
                lines.append(f"    Reason: {sv.change_reason}")
            lines.append("")

        return "\n".join(lines)
