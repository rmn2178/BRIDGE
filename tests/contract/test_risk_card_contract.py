"""Contract tests for RiskCard output stability."""

from __future__ import annotations

import json

from shared.models import RiskCard

EXPECTED_RISK_CARD_FIELDS = {
    "patient_id": str,
    "lace_plus_score": int,
    "risk_level": str,
    "primary_drivers": list,
    "medication_flags": list,
    "sdoh_flags": list,
    "pending_labs": list,
    "missing_follow_ups": list,
    "fhir_citations": list,
}


class TestRiskCardContract:
    """Protect RiskCard output shape and data types from regression."""

    def test_all_expected_fields_present(self, golden_risk_card: RiskCard) -> None:
        dumped = golden_risk_card.model_dump()
        assert set(dumped.keys()) == set(EXPECTED_RISK_CARD_FIELDS.keys())

    def test_field_types_match_expected(self, golden_risk_card: RiskCard) -> None:
        dumped = golden_risk_card.model_dump()
        for field, expected_type in EXPECTED_RISK_CARD_FIELDS.items():
            assert isinstance(dumped[field], expected_type)

    def test_primary_drivers_have_required_sub_fields(self, golden_risk_card: RiskCard) -> None:
        for driver in golden_risk_card.model_dump()["primary_drivers"]:
            assert set(driver.keys()) >= {"criterion", "points", "fhir_evidence"}
            assert isinstance(driver["criterion"], str)
            assert isinstance(driver["points"], int)
            assert isinstance(driver["fhir_evidence"], list)

    def test_risk_card_json_serializable(self, golden_risk_card: RiskCard) -> None:
        json.dumps(golden_risk_card.model_dump())

    def test_risk_card_json_deserializable(self, golden_risk_card: RiskCard) -> None:
        json_str = golden_risk_card.model_dump_json()
        parsed = RiskCard.model_validate_json(json_str)
        assert parsed == golden_risk_card

    def test_risk_level_is_valid_enum_string(self, golden_risk_card: RiskCard) -> None:
        assert golden_risk_card.risk_level in ["LOW", "MODERATE", "HIGH", "VERY_HIGH"]
