"""TypedDict definitions for core FHIR resources."""

from __future__ import annotations

from typing import List, NotRequired, TypedDict


class Coding(TypedDict, total=False):
    system: str
    code: str
    display: str


class CodeableConcept(TypedDict, total=False):
    text: str
    coding: List[Coding]


class Period(TypedDict, total=False):
    start: str
    end: str


Encounter = TypedDict(
    "Encounter",
    {
        "id": str,
        "status": str,
        "class": dict,
        "period": Period,
        "reasonCode": List[CodeableConcept],
    },
    total=False,
)


class Condition(TypedDict, total=False):
    id: str
    clinicalStatus: dict
    code: CodeableConcept


class MedicationRequest(TypedDict, total=False):
    id: str
    status: str
    medicationCodeableConcept: CodeableConcept
    dosageInstruction: List[dict]


class Observation(TypedDict, total=False):
    id: str
    status: str
    code: CodeableConcept
    valueCodeableConcept: CodeableConcept
    effectiveDateTime: str
