"""Care plan generation logic for BRIDGE."""

from __future__ import annotations

from typing import List

from shared.models import CarePlanAction, CarePlanOutput, RiskCard


def generate_care_plan(risk_card: RiskCard) -> CarePlanOutput:
    """Generate deterministic care plan actions and summaries."""

    actions: List[CarePlanAction] = []

    if "warfarin" in risk_card.medication_flags:
        actions.append(
            CarePlanAction(
                action="Schedule INR testing within 72 hours",
                priority="CRITICAL",
                rationale="High-risk anticoagulation requires monitoring.",
                risk_card_source="medication_flags",
            )
        )

    if "furosemide" in risk_card.medication_flags:
        actions.append(
            CarePlanAction(
                action="Daily weight check; diuretic dose review at follow-up",
                priority="HIGH",
                rationale="Diuretic therapy needs close weight monitoring.",
                risk_card_source="medication_flags",
            )
        )

    for driver in risk_card.primary_drivers:
        if "chf" in driver.criterion.lower() or "heart failure" in driver.criterion.lower():
            actions.append(
                CarePlanAction(
                    action=(
                        "Daily weight monitoring. Alert PCP if >2lb gain in 24h "
                        "or >5lb in 1 week."
                    ),
                    priority="HIGH",
                    rationale="CHF risk driver identified.",
                    risk_card_source="primary_drivers",
                )
            )
            break

    for item in risk_card.missing_follow_ups:
        actions.append(
            CarePlanAction(
                action=f"Schedule: {item}",
                priority="HIGH",
                rationale="Follow-up gap detected.",
                risk_card_source="missing_follow_ups",
            )
        )

    for item in risk_card.pending_labs:
        actions.append(
            CarePlanAction(
                action=f"Review and act on: {item}",
                priority="ROUTINE",
                rationale="Pending lab needs review.",
                risk_card_source="pending_labs",
            )
        )

    for flag in risk_card.sdoh_flags:
        flag_lower = flag.lower()
        if "living alone" in flag_lower or "z60.2" in flag_lower:
            actions.append(
                CarePlanAction(
                    action="Arrange home health nursing visit within 48 hours",
                    priority="HIGH",
                    rationale="SDoH risk for limited home support.",
                    risk_card_source="sdoh_flags",
                )
            )
        if "z59" in flag_lower:
            actions.append(
                CarePlanAction(
                    action="Connect patient with social worker for resource navigation",
                    priority="ROUTINE",
                    rationale="Housing or food insecurity risk.",
                    risk_card_source="sdoh_flags",
                )
            )

    patient_instructions = (
        "Take your medicines exactly as prescribed. Weigh yourself every morning and "
        "call your doctor if you gain more than 2 pounds in a day or more than 5 pounds "
        "in a week. A home nurse will visit to check on you. Schedule your follow-up "
        "visit right away and keep all lab appointments. Call 911 if you have chest pain, "
        "trouble breathing, fainting, or sudden swelling."
    )

    critical_actions = [a.action for a in actions if a.priority == "CRITICAL"]
    critical_text = ", ".join(critical_actions) if critical_actions else "None"

    clinician_summary = (
        f"Generated {len(actions)} care actions for LACE+ "
        f"{risk_card.lace_plus_score} {risk_card.risk_level} patient. "
        f"Critical flags: {critical_text}."
    )

    return CarePlanOutput(
        patient_id=risk_card.patient_id,
        actions=actions,
        patient_instructions=patient_instructions,
        clinician_summary=clinician_summary,
    )
