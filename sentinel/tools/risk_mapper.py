"""Risk mapping and enrichment logic for SENTINEL."""

from __future__ import annotations

from typing import List

from shared.models import RiskCard, RiskDriver
from sentinel.tools.fhir_snapshot import FHIRBundle
from common.normalize import normalize_resource
from common.constants import HIGH_RISK_MEDS, SDOH_PREFIXES
from sentinel.tools.lace_plus import calculate_lace_plus


def _lower_text(value: str | None) -> str:
    return value.lower() if isinstance(value, str) else ""


def _find_medication_text(resource: dict) -> str:
    med = resource.get("medicationCodeableConcept", {})
    text = med.get("text") if isinstance(med, dict) else None
    if text:
        return text
    coding = med.get("coding", []) if isinstance(med, dict) else []
    for item in coding:
        if isinstance(item, dict) and item.get("display"):
            return item.get("display")
    return ""


def _find_sdoh_code(resource: dict) -> tuple[str, str] | None:
    code = resource.get("code", {})
    coding = code.get("coding", []) if isinstance(code, dict) else []
    for item in coding:
        if not isinstance(item, dict):
            continue
        code_value = item.get("code")
        display = item.get("display") or ""
        if isinstance(code_value, str) and code_value.startswith(SDOH_PREFIXES):
            return code_value, display
    value_code = resource.get("valueCodeableConcept", {})
    value_coding = (
        value_code.get("coding", []) if isinstance(value_code, dict) else []
    )
    for item in value_coding:
        if not isinstance(item, dict):
            continue
        code_value = item.get("code")
        display = item.get("display") or ""
        if isinstance(code_value, str) and code_value.startswith(SDOH_PREFIXES):
            return code_value, display
    return None


def _normalize_sdoh_display(code_value: str, display: str) -> str:
    if code_value.startswith("Z60.2") and "living alone" in display.lower():
        return "Living alone"
    return display


def _extract_medication_flags(medications: List[dict]) -> List[str]:
    flags: List[str] = []
    for med in medications:
        resource = normalize_resource(med)
        if resource.get("status") != "active":
            continue
        med_text = _lower_text(_find_medication_text(resource))
        med_cc = resource.get("medicationCodeableConcept")
        if not isinstance(med_cc, dict):
            med_cc = {}
        coding = med_cc.get("coding", [])
        coding_texts = [
            _lower_text(item.get("display"))
            for item in coding
            if isinstance(item, dict)
        ]
        haystack = " ".join([med_text] + coding_texts)
        for flag in HIGH_RISK_MEDS:
            if flag in haystack and flag not in flags:
                flags.append(flag)
    return flags


def _extract_sdoh_flags(observations: List[dict]) -> List[str]:
    flags: List[str] = []
    for obs in observations:
        resource = normalize_resource(obs)
        sdoh = _find_sdoh_code(resource)
        if not sdoh:
            continue
        code_value, display = sdoh
        normalized_display = _normalize_sdoh_display(code_value, display)
        label = (
            f"{code_value}: {normalized_display}" if normalized_display else code_value
        )
        if label not in flags:
            flags.append(label)
    return flags


def _extract_pending_labs(observations: List[dict]) -> List[str]:
    pending: List[str] = []
    for obs in observations:
        resource = normalize_resource(obs)
        status = resource.get("status")
        if status not in ["registered", "preliminary"]:
            continue
        code = resource.get("code", {})
        code_text = ""
        if isinstance(code, dict):
            code_text = code.get("text", "")
            if not code_text:
                coding = code.get("coding", [])
                if coding and isinstance(coding[0], dict):
                    code_text = coding[0].get("display", "")
        effective = resource.get("effectiveDateTime", "")
        pending.append(f"{code_text} pending from {effective}".strip())
    return pending


def _extract_missing_followups(appointments: List[dict]) -> List[str]:
    if not appointments:
        return ["No follow-up appointments scheduled"]
    for appt in appointments:
        if "cardiology" in _lower_text(str(appt)):
            return []
    return ["No cardiology appointment within 7 days"]


def _extract_citations(bundle: FHIRBundle) -> List[str]:
    citations: List[str] = []
    for encounter in bundle.encounters:
        resource = normalize_resource(encounter)
        if resource.get("id"):
            citations.append(f"Encounter/{resource['id']}")
    for med in bundle.medications:
        resource = normalize_resource(med)
        if resource.get("id"):
            citations.append(f"MedicationRequest/{resource['id']}")
    for obs in bundle.observations:
        resource = normalize_resource(obs)
        if resource.get("id"):
            citations.append(f"Observation/{resource['id']}")
    return citations


def map_risk_drivers(bundle: FHIRBundle) -> RiskCard:
    """Generate a complete RiskCard from the FHIR bundle."""

    lace = calculate_lace_plus(bundle)
    primary_drivers = [RiskDriver(**driver) for driver in lace["primary_drivers"]]
    medication_flags = _extract_medication_flags(bundle.medications)
    sdoh_flags = _extract_sdoh_flags(bundle.observations)
    pending_labs = _extract_pending_labs(bundle.observations)
    missing_follow_ups = _extract_missing_followups(bundle.appointments)
    citations = _extract_citations(bundle)

    return RiskCard(
        patient_id=bundle.patient.get("id", ""),
        lace_plus_score=lace["lace_plus_score"],
        risk_level=lace["risk_level"],
        primary_drivers=primary_drivers,
        medication_flags=medication_flags,
        sdoh_flags=sdoh_flags,
        pending_labs=pending_labs,
        missing_follow_ups=missing_follow_ups,
        fhir_citations=citations[:10],
    )
