"""
Entity-level data comparison for change detection.

Compares extracted JSON entities across crawls to detect content changes
at the data level. Catches changes that DOM and visual diffing miss
(e.g., price changes, new products, removed items).

Uses JSON deep diff with type change detection and configurable
sensitivity for numeric vs string changes.

References:
    - Phase4.md Step 4.4: Entity-level comparison
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class FieldChange:
    """A change in a single field between two entity snapshots."""

    field_name: str
    change_type: str  # "added", "removed", "modified", "type_changed"
    old_value: Any = None
    new_value: Any = None
    significance: float = 1.0


@dataclass
class EntityDiffResult:
    """Result of entity-level comparison."""

    similarity: float  # 0-1 overall similarity
    changes: list[FieldChange] = field(default_factory=list)
    entities_compared: int = 0
    fields_unchanged: int = 0
    fields_changed: int = 0
    fields_added: int = 0
    fields_removed: int = 0

    @property
    def change_ratio(self) -> float:
        total = self.fields_unchanged + self.fields_changed + self.fields_added + self.fields_removed
        if total == 0:
            return 0.0
        return (self.fields_changed + self.fields_added + self.fields_removed) / total


class EntityDiffer:
    """Compare extracted entities across crawl snapshots.

    Usage:
        differ = EntityDiffer()
        result = differ.compare(
            old_data={"name": "Widget", "price": 29.99},
            new_data={"name": "Widget Pro", "price": 34.99, "sku": "WP-001"},
        )

        for change in result.changes:
            print(f"{change.change_type}: {change.field_name}")
    """

    def __init__(
        self,
        numeric_tolerance: float = 0.01,
        ignore_fields: set[str] | None = None,
    ):
        self.numeric_tolerance = numeric_tolerance
        self.ignore_fields = ignore_fields or {"_id", "timestamp", "crawl_id"}

    def compare(
        self,
        old_data: dict | list[dict],
        new_data: dict | list[dict],
    ) -> EntityDiffResult:
        """Compare old and new entity data.

        Args:
            old_data: Previous extraction result (dict or list of dicts).
            new_data: Current extraction result.

        Returns:
            EntityDiffResult with field-level changes.
        """
        # Normalize to lists
        if isinstance(old_data, dict):
            old_data = [old_data]
        if isinstance(new_data, dict):
            new_data = [new_data]

        all_changes: list[FieldChange] = []
        total_unchanged = 0
        total_changed = 0
        total_added = 0
        total_removed = 0

        # Compare matching entities
        max_entities = max(len(old_data), len(new_data))
        for i in range(max_entities):
            old_entity = old_data[i] if i < len(old_data) else {}
            new_entity = new_data[i] if i < len(new_data) else {}

            changes = self._diff_entities(old_entity, new_entity)
            all_changes.extend(changes)

            for c in changes:
                if c.change_type == "added":
                    total_added += 1
                elif c.change_type == "removed":
                    total_removed += 1
                elif c.change_type in ("modified", "type_changed"):
                    total_changed += 1

        # Count unchanged fields
        for i in range(min(len(old_data), len(new_data))):
            old_fields = set(old_data[i].keys()) - self.ignore_fields
            new_fields = set(new_data[i].keys()) - self.ignore_fields
            common = old_fields & new_fields
            changed_names = {c.field_name for c in all_changes}
            total_unchanged += len(common - changed_names)

        # Calculate similarity
        total = total_unchanged + total_changed + total_added + total_removed
        similarity = total_unchanged / total if total > 0 else 1.0

        return EntityDiffResult(
            similarity=similarity,
            changes=all_changes,
            entities_compared=max_entities,
            fields_unchanged=total_unchanged,
            fields_changed=total_changed,
            fields_added=total_added,
            fields_removed=total_removed,
        )

    def _diff_entities(
        self, old: dict, new: dict,
    ) -> list[FieldChange]:
        """Diff two individual entity dicts."""
        changes: list[FieldChange] = []

        old_fields = set(old.keys()) - self.ignore_fields
        new_fields = set(new.keys()) - self.ignore_fields

        # Added fields
        for f in new_fields - old_fields:
            changes.append(FieldChange(
                field_name=f,
                change_type="added",
                new_value=new[f],
                significance=0.7,
            ))

        # Removed fields
        for f in old_fields - new_fields:
            changes.append(FieldChange(
                field_name=f,
                change_type="removed",
                old_value=old[f],
                significance=0.8,
            ))

        # Modified fields
        for f in old_fields & new_fields:
            old_val = old[f]
            new_val = new[f]

            if type(old_val) != type(new_val):
                changes.append(FieldChange(
                    field_name=f,
                    change_type="type_changed",
                    old_value=old_val,
                    new_value=new_val,
                    significance=0.9,
                ))
            elif not self._values_equal(old_val, new_val):
                changes.append(FieldChange(
                    field_name=f,
                    change_type="modified",
                    old_value=old_val,
                    new_value=new_val,
                    significance=self._change_significance(f, old_val, new_val),
                ))

        return changes

    def _values_equal(self, a: Any, b: Any) -> bool:
        """Check if two values are equal with type-aware tolerance."""
        if a == b:
            return True

        # Numeric tolerance
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            max_val = max(abs(a), abs(b), 1e-10)
            return abs(a - b) / max_val <= self.numeric_tolerance

        # String normalization
        if isinstance(a, str) and isinstance(b, str):
            return a.strip().lower() == b.strip().lower()

        # List comparison
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                return False
            return all(self._values_equal(x, y) for x, y in zip(a, b))

        # Nested dict comparison
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a.keys()) != set(b.keys()):
                return False
            return all(self._values_equal(a[k], b[k]) for k in a)

        return False

    @staticmethod
    def _change_significance(field_name: str, old_val: Any, new_val: Any) -> float:
        """Rate how significant a field change is.

        Price changes and structural shifts are more significant
        than description text changes.
        """
        # High significance fields
        if any(keyword in field_name.lower()
               for keyword in ["price", "cost", "amount", "total"]):
            return 1.0

        # Medium significance
        if any(keyword in field_name.lower()
               for keyword in ["name", "title", "url", "status", "type"]):
            return 0.8

        # Numeric changes
        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            return 0.7

        # Text changes (lower significance for long text)
        if isinstance(old_val, str) and isinstance(new_val, str):
            if len(old_val) > 100 or len(new_val) > 100:
                return 0.4  # Long description changes are less significant
            return 0.6

        return 0.5
