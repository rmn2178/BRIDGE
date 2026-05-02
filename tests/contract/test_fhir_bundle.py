"""Contract tests for golden_patient.json structure and content."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

RAW_BUNDLE = json.loads(
    (Path(__file__).resolve().parents[2] / "sentinel" / "data" / "golden_patient.json").read_text(encoding="utf-8")
)


class TestFHIRBundleStructure:
    """Validate the golden FHIR bundle meets structural expectations."""

    def test_bundle_type_is_transaction_or_collection(self) -> None:
        assert RAW_BUNDLE["resourceType"] == "Bundle"
        assert RAW_BUNDLE["type"] in ["transaction", "collection", "searchset"]

    def test_has_entries(self) -> None:
        assert "entry" in RAW_BUNDLE and len(RAW_BUNDLE["entry"]) > 0

    def test_patient_resource_present(self) -> None:
        assert any(
            entry.get("resource", {}).get("resourceType") == "Patient"
            for entry in RAW_BUNDLE["entry"]
        )

    def test_patient_id_is_bridge_demo_001(self) -> None:
        patient = next(
            entry["resource"]
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Patient"
        )
        assert patient.get("id") == "bridge-demo-001"

    def test_exactly_3_conditions(self) -> None:
        assert len(
            [entry for entry in RAW_BUNDLE["entry"] if entry.get("resource", {}).get("resourceType") == "Condition"]
        ) == 3

    def test_exactly_7_medication_requests(self) -> None:
        assert len(
            [entry for entry in RAW_BUNDLE["entry"] if entry.get("resource", {}).get("resourceType") == "MedicationRequest"]
        ) == 7

    def test_warfarin_medication_present(self) -> None:
        meds = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "MedicationRequest"
        ]
        assert any(
            "warfarin" in (med.get("medicationCodeableConcept", {}).get("text", "").lower())
            or any("warfarin" in coding.get("display", "").lower() for coding in med.get("medicationCodeableConcept", {}).get("coding", []))
            for med in meds
        )

    def test_exactly_2_ed_encounters(self) -> None:
        encounters = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Encounter"
        ]
        assert len([enc for enc in encounters if enc.get("class", {}).get("code") == "EMER"]) == 2

    def test_inpatient_encounter_present(self) -> None:
        encounters = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Encounter"
        ]
        assert any(enc.get("class", {}).get("code") == "IMP" for enc in encounters)

    def test_inpatient_encounter_has_period(self) -> None:
        encounter = next(
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Encounter"
            and entry.get("resource", {}).get("class", {}).get("code") == "IMP"
        )
        assert "period" in encounter
        assert "start" in encounter["period"]
        assert "end" in encounter["period"]

    def test_los_is_6_days(self) -> None:
        encounter = next(
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Encounter"
            and entry.get("resource", {}).get("class", {}).get("code") == "IMP"
        )
        start = datetime.fromisoformat(encounter["period"]["start"]).date()
        end = datetime.fromisoformat(encounter["period"]["end"]).date()
        assert (end - start).days + 1 == 6

    def test_no_appointment_resources(self) -> None:
        assert len(
            [entry for entry in RAW_BUNDLE["entry"] if entry.get("resource", {}).get("resourceType") == "Appointment"]
        ) == 0

    def test_pending_bmp_observation_present(self) -> None:
        observations = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Observation"
        ]
        assert any(obs.get("status") in ["registered", "preliminary"] for obs in observations)

    def test_z60_sdoh_observation_present(self) -> None:
        observations = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Observation"
        ]
        assert any(
            any(coding.get("code", "").startswith("Z60") for coding in obs.get("code", {}).get("coding", []))
            for obs in observations
        )

    def test_z59_sdoh_observation_present(self) -> None:
        observations = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Observation"
        ]
        assert any(
            any(coding.get("code", "").startswith("Z59") for coding in obs.get("code", {}).get("coding", []))
            for obs in observations
        )

    def test_all_conditions_have_clinical_status(self) -> None:
        conditions = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "Condition"
        ]
        assert all(
            condition.get("clinicalStatus", {}).get("coding", [{}])[0].get("code") == "active"
            for condition in conditions
        )

    def test_all_medications_have_status_active(self) -> None:
        medications = [
            entry.get("resource", {})
            for entry in RAW_BUNDLE["entry"]
            if entry.get("resource", {}).get("resourceType") == "MedicationRequest"
        ]
        assert all(med.get("status") == "active" for med in medications)
