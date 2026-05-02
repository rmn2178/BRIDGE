"""Unit tests for CMS documentation gap auditing."""

from __future__ import annotations

from bridge_agent.tools.gap_audit import audit_documentation_gaps
from sentinel.tools.fhir_snapshot import FHIRBundle
from shared.models import GapAuditOutput, RiskCard


def _bundle_with_followup_and_meds() -> FHIRBundle:
    return FHIRBundle(
        patient={},
        conditions=[],
        medications=[{"resourceType": "MedicationRequest", "id": "med-1"}],
        observations=[],
        encounters=[],
        allergies=[],
        appointments=[{"resourceType": "Appointment", "id": "appt-1"}],
    )


class TestGapAuditGoldenPatient:
    """Validate gap audit results for the golden patient."""

    def test_overall_status_is_action_required(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        assert result.overall_status == "ACTION_REQUIRED"

    def test_has_exactly_5_items(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        assert len(result.items) == 5

    def test_followup_check_fails(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        item = next(i for i in result.items if "follow-up appointment" in i.requirement)
        assert item.status == "FAIL"

    def test_medication_check_passes(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        item = next(i for i in result.items if "medication reconciliation" in i.requirement.lower())
        assert item.status == "PASS"

    def test_patient_education_always_fails(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        item = next(i for i in result.items if "patient education" in i.requirement.lower())
        assert item.status == "FAIL"

    def test_pending_labs_check_fails(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        item = next(i for i in result.items if "pending labs" in i.requirement.lower())
        assert item.status == "FAIL"

    def test_high_risk_medication_check_fails(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        item = next(i for i in result.items if "high-risk medication" in i.requirement.lower())
        assert item.status == "FAIL"

    def test_all_fail_items_have_remediation(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        for item in result.items:
            if item.status == "FAIL":
                assert item.remediation

    def test_pass_items_have_no_remediation(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        for item in result.items:
            if item.status == "PASS":
                assert item.remediation is None


class TestGapAuditEdgeCases:
    """Validate gap audit behavior for edge cases."""

    def test_all_pass_when_fully_documented(self, minimal_risk_card: RiskCard) -> None:
        bundle = _bundle_with_followup_and_meds()
        result = audit_documentation_gaps(minimal_risk_card, bundle)
        fail_items = [item for item in result.items if item.status == "FAIL"]
        assert len(fail_items) == 1
        assert fail_items[0].requirement.lower().startswith("patient education")
        assert result.overall_status == "ACTION_REQUIRED"

    def test_empty_bundle_no_crash(self, minimal_risk_card: RiskCard, empty_bundle: FHIRBundle) -> None:
        result = audit_documentation_gaps(minimal_risk_card, empty_bundle)
        assert isinstance(result, GapAuditOutput)
