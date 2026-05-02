"""Unit tests for RiskCard mapping and enrichment logic."""

from __future__ import annotations

from sentinel.tools.fhir_snapshot import FHIRBundle
from sentinel.tools.risk_mapper import map_risk_drivers


def _make_medication(name: str, status: str = "active") -> dict:
    return {
        "resourceType": "MedicationRequest",
        "id": f"{name}-001",
        "status": status,
        "medicationCodeableConcept": {
            "text": name,
            "coding": [{"display": name}],
        },
    }


def _make_appointment() -> dict:
    return {"resourceType": "Appointment", "id": "appt-1"}


class TestRiskMapperGoldenPatient:
    """Validate RiskCard enrichment for golden patient data."""

    def test_returns_risk_card_type(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        from shared.models import RiskCard

        assert isinstance(risk_card, RiskCard)

    def test_warfarin_flagged(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert "warfarin" in risk_card.medication_flags

    def test_furosemide_flagged(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert "furosemide" in risk_card.medication_flags

    def test_sdoh_z60_flagged(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert any(flag.startswith("Z60") for flag in risk_card.sdoh_flags)

    def test_sdoh_z59_flagged(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert any(flag.startswith("Z59") for flag in risk_card.sdoh_flags)

    def test_bmp_in_pending_labs(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert any(
            "bmp" in lab.lower() or "metabolic" in lab.lower()
            for lab in risk_card.pending_labs
        )

    def test_missing_followup_flagged(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert risk_card.missing_follow_ups

    def test_fhir_citations_not_empty(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert len(risk_card.fhir_citations) >= 1

    def test_fhir_citations_max_10(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert len(risk_card.fhir_citations) <= 10

    def test_patient_id_propagated(self, golden_patient_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert risk_card.patient_id == "bridge-demo-001"


class TestRiskMapperEdgeCases:
    """Validate edge conditions for medication and appointment logic."""

    def test_no_medications_no_flags(self, empty_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(empty_bundle)
        assert risk_card.medication_flags == []

    def test_no_observations_no_sdoh(self, empty_bundle: FHIRBundle) -> None:
        risk_card = map_risk_drivers(empty_bundle)
        assert risk_card.sdoh_flags == []

    def test_appointments_present_clears_missing_followup(self) -> None:
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[],
            observations=[],
            encounters=[],
            allergies=[],
            appointments=[_make_appointment()],
        )
        risk_card = map_risk_drivers(bundle)
        assert "No follow-up appointments scheduled" not in risk_card.missing_follow_ups

    def test_medication_deduplication(self) -> None:
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[_make_medication("warfarin"), _make_medication("warfarin")],
            observations=[],
            encounters=[],
            allergies=[],
            appointments=[],
        )
        risk_card = map_risk_drivers(bundle)
        assert risk_card.medication_flags.count("warfarin") == 1

    def test_non_active_medications_not_flagged(self) -> None:
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[_make_medication("warfarin", status="stopped")],
            observations=[],
            encounters=[],
            allergies=[],
            appointments=[],
        )
        risk_card = map_risk_drivers(bundle)
        assert "warfarin" not in risk_card.medication_flags
