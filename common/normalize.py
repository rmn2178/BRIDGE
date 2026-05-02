"""FHIR resource normalization helpers."""

from __future__ import annotations

from typing import Any, Dict


def normalize_resource(item: Dict[str, Any]) -> Dict[str, Any]:
    """Return the resource dict regardless of entry wrapper."""

    if "resource" in item and isinstance(item.get("resource"), dict):
        return item["resource"]
    return item
