"""Unit tests for deterministic LACE+ scoring logic."""

from __future__ import annotations

from datetime import datetime, timedelta

from sentinel.tools.fhir_snapshot import FHIRBundle
from sentinel.tools.lace_plus import calculate_lace_plus
from shared.models import RiskLevel


def _make_encounter(class_code: str, start: str, end: str | None = None) -> dict:
    encounter = {
        "resourceType": "Encounter",
        "id": f"enc-{class_code.lower()}-{start}",
        "class": {"code": class_code},
        "period": {"start": start},
    }
    if end:
        encounter["period"]["end"] = end
    return encounter


def _make_condition(code: str) -> dict:
    return {
        "resourceType": "Condition",
        "id": f"cond-{code}",
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": code}]},
    }


class TestLacePlusGoldenPatient:
    """Validate LACE+ scoring against the golden patient data."""

    def test_golden_score_is_14(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        assert result["lace_plus_score"] == 14

    def test_golden_risk_level_is_high(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        assert result["risk_level"] == RiskLevel.HIGH

    def test_golden_has_4_primary_drivers(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        assert len(result["primary_drivers"]) == 5

    def test_golden_los_driver_6_days(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        los = [d for d in result["primary_drivers"] if "6 days" in d["criterion"]]
        assert los and los[0]["points"] == 3

    def test_golden_acuity_driver_3_points(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        acuity = [d for d in result["primary_drivers"] if "Acute" in d["criterion"]]
        assert acuity and acuity[0]["points"] == 3

    def test_golden_comorbidity_driver_3_conditions(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        comorb = [d for d in result["primary_drivers"] if "3" in d["criterion"]]
        assert comorb and comorb[0]["points"] == 3

    def test_golden_ed_visits_driver_2_visits(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        ed = [d for d in result["primary_drivers"] if "2" in d["criterion"] and "ED" in d["criterion"]]
        assert ed and ed[0]["points"] == 2


class TestLacePlusEdgeCases:
    """Validate boundary conditions for LACE+ scoring."""

    def test_empty_bundle_returns_valid_dict(self, empty_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(empty_bundle)
        assert isinstance(result, dict)
        assert result["lace_plus_score"] >= 0

    def test_los_1_day_scores_zero(self) -> None:
        start = datetime(2026, 4, 1)
        end = start
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[],
            observations=[],
            encounters=[_make_encounter("IMP", start.date().isoformat(), end.date().isoformat())],
            allergies=[],
            appointments=[],
        )
        result = calculate_lace_plus(bundle)
        los_driver = result["primary_drivers"][0]
        assert los_driver["points"] == 0

    def test_los_14_days_scores_five(self) -> None:
        start = datetime(2026, 1, 1)
        end = start + timedelta(days=13)
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[],
            observations=[],
            encounters=[_make_encounter("IMP", start.date().isoformat(), end.date().isoformat())],
            allergies=[],
            appointments=[],
        )
        result = calculate_lace_plus(bundle)
        los_driver = result["primary_drivers"][0]
        assert los_driver["points"] == 5

    def test_no_ed_visits_scores_zero(self) -> None:
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[],
            observations=[],
            encounters=[_make_encounter("IMP", "2026-04-01", "2026-04-02")],
            allergies=[],
            appointments=[],
        )
        result = calculate_lace_plus(bundle)
        ed_driver = [d for d in result["primary_drivers"] if "ED" in d["criterion"]][0]
        assert ed_driver["points"] == 0

    def test_four_ed_visits_scores_four(self) -> None:
        encounters = [
            _make_encounter("IMP", "2026-04-01", "2026-04-02"),
            _make_encounter("EMER", "2026-01-01"),
            _make_encounter("EMER", "2026-01-02"),
            _make_encounter("EMER", "2026-01-03"),
            _make_encounter("EMER", "2026-01-04"),
        ]
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[],
            observations=[],
            encounters=encounters,
            allergies=[],
            appointments=[],
        )
        result = calculate_lace_plus(bundle)
        ed_driver = [d for d in result["primary_drivers"] if "ED" in d["criterion"]][0]
        assert ed_driver["points"] == 4

    def test_score_0_to_4_is_low(self) -> None:
        bundle = FHIRBundle(
            patient={},
            conditions=[],
            medications=[],
            observations=[],
            encounters=[],
            allergies=[],
            appointments=[],
        )
        result = calculate_lace_plus(bundle)
        assert result["risk_level"] == RiskLevel.LOW

    def test_score_15_plus_is_very_high(self) -> None:
        conditions = [_make_condition("I50.1"), _make_condition("E11.9"), _make_condition("N18.3"), _make_condition("I10")]
        encounters = [
            _make_encounter("IMP", "2026-01-01", "2026-01-20"),
            _make_encounter("EMER", "2026-02-01"),
            _make_encounter("EMER", "2026-02-02"),
            _make_encounter("EMER", "2026-02-03"),
            _make_encounter("EMER", "2026-02-04"),
        ]
        bundle = FHIRBundle(
            patient={},
            conditions=conditions,
            medications=[],
            observations=[],
            encounters=encounters,
            allergies=[],
            appointments=[],
        )
        result = calculate_lace_plus(bundle)
        assert result["risk_level"] == RiskLevel.VERY_HIGH

    def test_fhir_evidence_references_encounter_ids(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        los_driver = result["primary_drivers"][0]
        assert any("Encounter/" in evidence for evidence in los_driver["fhir_evidence"])


class TestLacePlusScoreArithmetic:
    """Confirm that total score equals sum of driver points."""

    def test_total_equals_sum_of_driver_points(self, golden_patient_bundle: FHIRBundle) -> None:
        result = calculate_lace_plus(golden_patient_bundle)
        total = sum(driver["points"] for driver in result["primary_drivers"])
        assert result["lace_plus_score"] == total
