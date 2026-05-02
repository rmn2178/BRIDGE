"""Unit tests for PCP handoff letter generation."""

from __future__ import annotations

from bridge_agent.tools.pcp_handoff import draft_pcp_handoff
from sentinel.tools.fhir_snapshot import FHIRBundle
from shared.models import PCPHandoff, RiskCard


class TestPCPHandoffGoldenPatient:
    """Validate PCP handoff letter content for golden patient."""

    def test_returns_pcp_handoff_type(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert isinstance(result, PCPHandoff)

    def test_letter_minimum_length(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert len(result.handoff_letter) >= 300

    def test_letter_contains_patient_id(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert golden_risk_card.patient_id in result.handoff_letter

    def test_letter_mentions_chf(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        letter = result.handoff_letter.lower()
        assert "chf" in letter or "heart failure" in letter

    def test_letter_mentions_warfarin_concern(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        letter = result.handoff_letter.lower()
        midpoint = len(letter) // 2
        first_half = letter[:midpoint]
        assert "warfarin" in first_half or "inr" in first_half

    def test_letter_contains_fhir_citations(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert "MedicationRequest/" in result.handoff_letter

    def test_medication_changes_non_empty(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert len(result.medication_changes) >= 1

    def test_medication_changes_cite_fhir_ids(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert any("MedicationRequest/" in med for med in result.medication_changes)

    def test_follow_up_priorities_non_empty(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert len(result.follow_up_priorities) >= 1

    def test_hospitalization_reason_not_empty(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert result.hospitalization_reason

    def test_lace_score_in_letter(self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert str(golden_risk_card.lace_plus_score) in result.handoff_letter


class TestPCPHandoffEdgeCases:
    """Validate PCP handoff behavior for minimal inputs."""

    def test_empty_medications_produces_valid_handoff(self, minimal_risk_card: RiskCard, empty_bundle: FHIRBundle) -> None:
        result = draft_pcp_handoff(minimal_risk_card, empty_bundle)
        assert isinstance(result, PCPHandoff)
        assert result.medication_changes == []
