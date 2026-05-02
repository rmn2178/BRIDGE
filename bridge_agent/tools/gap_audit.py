"""CMS documentation gap audit logic for BRIDGE."""

from __future__ import annotations

from typing import List

from shared.models import GapAuditItem, GapAuditOutput, RiskCard
from sentinel.tools.fhir_snapshot import FHIRBundle


def audit_documentation_gaps(risk_card: RiskCard, bundle: FHIRBundle) -> GapAuditOutput:
    """Audit discharge documentation gaps based on FHIR bundle data."""

    items: List[GapAuditItem] = []

    has_follow_up = bool(bundle.appointments)
    items.append(
        GapAuditItem(
            requirement="follow-up appointment scheduled within 7 days",
            status="PASS" if has_follow_up else "FAIL",
            fhir_evidence="Appointment" if has_follow_up else None,
            remediation=(
                None if has_follow_up else "Schedule PCP or cardiology follow-up before discharge"
            ),
        )
    )

    has_medications = bool(bundle.medications)
    items.append(
        GapAuditItem(
            requirement="Medication reconciliation completed",
            status="PASS" if has_medications else "FAIL",
            fhir_evidence="MedicationRequest" if has_medications else None,
            remediation=(
                None if has_medications else "Complete med rec and document in discharge summary"
            ),
        )
    )

    items.append(
        GapAuditItem(
            requirement="Patient education documented",
            status="FAIL",
            remediation="Document that patient received and understood discharge instructions",
        )
    )

    has_pending_labs = bool(risk_card.pending_labs)
    items.append(
        GapAuditItem(
            requirement="All pending labs reviewed and follow-up plan documented",
            status="FAIL" if has_pending_labs else "PASS",
            fhir_evidence=(
                ", ".join(risk_card.pending_labs) if has_pending_labs else None
            ),
            remediation=(
                None
                if not has_pending_labs
                else f"Review pending labs: {', '.join(risk_card.pending_labs)}"
            ),
        )
    )

    high_risk_meds = bool(risk_card.medication_flags)
    needs_monitoring = high_risk_meds and not has_follow_up
    items.append(
        GapAuditItem(
            requirement="High-risk medication monitoring plan in place",
            status="FAIL" if needs_monitoring else "PASS",
            remediation=(
                None if not needs_monitoring else "Schedule INR/monitoring for anticoagulation"
            ),
        )
    )

    overall_status = "ACTION_REQUIRED" if any(item.status == "FAIL" for item in items) else "PASS"

    return GapAuditOutput(
        patient_id=risk_card.patient_id,
        overall_status=overall_status,
        items=items,
    )
