"""Centralized constants and defaults for BRIDGE."""

from __future__ import annotations

from typing import Final

RISK_THRESHOLDS: Final[list[tuple[int, str]]] = [
    (4, "LOW"),
    (9, "MODERATE"),
    (14, "HIGH"),
]

HIGH_RISK_MEDS: Final[list[str]] = [
    "warfarin",
    "insulin",
    "opioid",
    "morphine",
    "fentanyl",
    "oxycodone",
    "furosemide",
    "digoxin",
    "lithium",
    "methotrexate",
    "heparin",
]

SDOH_PREFIXES: Final[tuple[str, ...]] = ("Z59", "Z60", "Z62", "Z63", "Z64", "Z65")

DEFAULT_FHIR_BASE_URL: Final[str] = "https://hapi.fhir.org/baseR4"
