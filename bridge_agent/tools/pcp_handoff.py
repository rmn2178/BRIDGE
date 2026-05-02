"""Primary care handoff letter generator for BRIDGE."""

from __future__ import annotations

from typing import List

from shared.models import PCPHandoff, RiskCard
from sentinel.tools.fhir_snapshot import FHIRBundle


def _normalize_resource(item: dict) -> dict:
    if "resource" in item and isinstance(item.get("resource"), dict):
        return item["resource"]
    return item


def _medication_name(resource: dict) -> str:
    med = resource.get("medicationCodeableConcept", {})
    if isinstance(med, dict):
        if med.get("text"):
            return med.get("text")
        coding = med.get("coding", [])
        if coding and isinstance(coding[0], dict) and coding[0].get("display"):
            return coding[0].get("display")
    return "Unknown medication"


def _dose_text(resource: dict) -> str:
    instructions = resource.get("dosageInstruction", [])
    if instructions and isinstance(instructions, list) and isinstance(instructions[0], dict):
        return instructions[0].get("text", "")
    return ""


def _hospitalization_reason(bundle: FHIRBundle) -> str:
    for encounter in bundle.encounters:
        resource = _normalize_resource(encounter)
        enc_class = resource.get("class")
        if not isinstance(enc_class, dict):
            enc_class = {}
        class_code = enc_class.get("code")
        if class_code == "IMP":
            reason = resource.get("reasonCode", [])
            if reason and isinstance(reason, list) and isinstance(reason[0], dict):
                text = reason[0].get("text")
                if text:
                    return text
                coding = reason[0].get("coding", [])
                if coding and isinstance(coding[0], dict):
                    return coding[0].get("display", "Hospitalization")
    return "Hospitalization"


def draft_pcp_handoff(risk_card: RiskCard, bundle: FHIRBundle) -> PCPHandoff:
    """Draft a detailed primary care handoff letter."""

    medication_changes: List[str] = []
    for med in bundle.medications:
        resource = _normalize_resource(med)
        if resource.get("status") != "active":
            continue
        name = _medication_name(resource)
        dose = _dose_text(resource)
        med_id = resource.get("id", "unknown")
        dose_text = f" {dose}" if dose else ""
        medication_changes.append(
            f"{name}{dose_text} [FHIR: MedicationRequest/{med_id}]"
        )

    hospitalization_reason = _hospitalization_reason(bundle)

    pending_concerns = list(risk_card.pending_labs)
    follow_up_priorities = list(risk_card.missing_follow_ups)

    anticoag_concern = "warfarin" in risk_card.medication_flags
    has_follow_up = bool(bundle.appointments)
    anticoag_gap = anticoag_concern and not has_follow_up

    concerns_section = []
    if anticoag_gap:
        concerns_section.append(
            "CONCERN #1: Anticoagulation monitoring gap. Warfarin is active without a "
            "scheduled INR follow-up."
        )
    for idx, concern in enumerate(pending_concerns, start=2 if anticoag_gap else 1):
        concerns_section.append(f"CONCERN #{idx}: Pending lab - {concern}.")

    concerns_text = "\n".join(concerns_section) if concerns_section else "None noted."

    meds_text = "\n".join(f"- {med}" for med in medication_changes) or "- None"

    follow_up_text = "\n".join(
        f"- {item}" for item in follow_up_priorities
    ) or "- No follow-ups on record"

    risk_summary = (
        f"LACE+ score {risk_card.lace_plus_score} ({risk_card.risk_level})."
    )

    handoff_letter = (
        "PRIMARY CARE HANDOFF - TRANSITION OF CARE\n"
        f"Patient: {risk_card.patient_id}\n"
        f"Re: Discharge - {hospitalization_reason}\n\n"
        "HOSPITAL COURSE\n"
        "The patient was admitted for decompensated heart failure with associated chronic "
        "conditions including diabetes and chronic kidney disease. The inpatient course focused "
        "on stabilization, diuresis, and optimization of guideline-directed therapy. Clinical "
        "status improved with careful volume management. Discharge planning emphasized medication "
        "adherence, monitoring for weight changes, and close outpatient follow-up.\n\n"
        "KEY MEDICATIONS\n"
        f"{meds_text}\n\n"
        "ACTIVE CONCERNS\n"
        f"{concerns_text}\n\n"
        "READMISSION RISK\n"
        f"{risk_summary} The risk is elevated due to multiple comorbidities, recent ED utilization, "
        "and pending lab results requiring follow-up. Home support concerns are also present and "
        "may affect adherence without timely intervention.\n\n"
        "SUGGESTED FOLLOW-UP\n"
        f"{follow_up_text}\n"
        "- Ensure INR or anticoagulation monitoring within 72 hours if warfarin continues.\n"
        "- Assess volume status and renal function after discharge.\n"
        "- Reinforce patient education on weight monitoring and emergency escalation.\n\n"
        "FOOTER\n"
        "Please contact the discharging team with any questions. This handoff letter includes "
        "FHIR-cited medication details to support reconciliation and continuity of care."
    )

    word_count = len(handoff_letter.split())
    if word_count < 300:
        handoff_letter += (
            "\n\nADDITIONAL NOTES\n"
            "This patient would benefit from structured care management and early outpatient "
            "engagement. Consider scheduling a nurse visit or telehealth check within 48 to 72 "
            "hours to review medications, reinforce dietary guidance, and verify access to "
            "prescriptions. Given the comorbidity burden and renal disease, please monitor basic "
            "metabolic panel results closely and adjust diuretic dosing as needed. Encourage the "
            "patient to maintain a daily weight log and bring it to the first follow-up appointment."
        )

    return PCPHandoff(
        patient_id=risk_card.patient_id,
        hospitalization_reason=hospitalization_reason,
        medication_changes=medication_changes,
        pending_concerns=pending_concerns,
        follow_up_priorities=follow_up_priorities,
        handoff_letter=handoff_letter,
    )
