"""Unit tests for Pydantic models and schema validation."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from shared.models import (
    CarePlanAction,
    GapAuditItem,
    GapAuditOutput,
    RiskCard,
    RiskLevel,
    SHARPContext,
)


class TestRiskLevel:
    """Validate RiskLevel enum serialization and enforcement."""

    def test_all_enum_values_serialize_to_string(self) -> None:
        assert RiskLevel.LOW.value == "LOW"
        assert RiskLevel.MODERATE.value == "MODERATE"
        assert RiskLevel.HIGH.value == "HIGH"
        assert RiskLevel.VERY_HIGH.value == "VERY_HIGH"

    def test_invalid_enum_raises_validation_error(self) -> None:
        with pytest.raises(ValueError):
            RiskLevel("INVALID")


class TestSHARPContext:
    """Validate SHARPContext construction and defaults."""

    def test_valid_full_construction(self) -> None:
        ctx = SHARPContext(
            patient_id="bridge-demo-001",
            fhir_base_url="https://hapi.fhir.org/baseR4",
            access_token="token",
            encounter_id="Enc/index-001",
            practitioner_id="Practitioner/123",
        )
        assert ctx.patient_id == "bridge-demo-001"
        assert ctx.encounter_id == "Enc/index-001"
        assert ctx.practitioner_id == "Practitioner/123"

    def test_optional_fields_default_to_none(self) -> None:
        ctx = SHARPContext(
            patient_id="bridge-demo-001",
            fhir_base_url="https://hapi.fhir.org/baseR4",
            access_token="",
        )
        assert ctx.encounter_id is None
        assert ctx.practitioner_id is None

    def test_empty_patient_id_allowed(self) -> None:
        ctx = SHARPContext(
            patient_id="",
            fhir_base_url="https://hapi.fhir.org/baseR4",
            access_token="",
        )
        assert ctx.patient_id == ""


class TestRiskCard:
    """Validate RiskCard schema extra example and round-trip behavior."""

    def test_constructs_from_schema_extra_example(self) -> None:
        example = RiskCard.model_config["json_schema_extra"]["example"]
        risk_card = RiskCard.model_validate(example)
        assert risk_card.patient_id == "bridge-demo-001"

    def test_model_dump_round_trip(self) -> None:
        example = RiskCard.model_config["json_schema_extra"]["example"]
        risk_card = RiskCard.model_validate(example)
        dumped = risk_card.model_dump()
        rehydrated = RiskCard.model_validate(dumped)
        assert rehydrated.patient_id == risk_card.patient_id

    def test_model_dump_json_is_valid_json(self) -> None:
        example = RiskCard.model_config["json_schema_extra"]["example"]
        risk_card = RiskCard.model_validate(example)
        payload = risk_card.model_dump_json()
        parsed = json.loads(payload)
        assert parsed["patient_id"] == "bridge-demo-001"

    def test_fhir_citations_accepts_empty_list(self) -> None:
        example = RiskCard.model_config["json_schema_extra"]["example"]
        example["fhir_citations"] = []
        risk_card = RiskCard.model_validate(example)
        assert risk_card.fhir_citations == []

    def test_very_high_risk_level_validates(self) -> None:
        example = RiskCard.model_config["json_schema_extra"]["example"]
        example["risk_level"] = "VERY_HIGH"
        risk_card = RiskCard.model_validate(example)
        assert risk_card.risk_level == RiskLevel.VERY_HIGH


class TestCarePlanAction:
    """Validate care plan action priorities."""

    def test_priority_must_be_valid_value(self) -> None:
        with pytest.raises(ValidationError):
            CarePlanAction(
                action="Test",
                priority="INVALID",
                rationale="test",
                risk_card_source="unit",
            )


class TestGapAuditItem:
    """Validate gap audit item status and optional fields."""

    def test_status_must_be_valid_value(self) -> None:
        with pytest.raises(ValidationError):
            GapAuditItem(requirement="Check", status="UNKNOWN")

    def test_optional_fields_accept_none(self) -> None:
        item = GapAuditItem(requirement="Check", status="PASS")
        assert item.fhir_evidence is None
        assert item.remediation is None


class TestGapAuditOutput:
    """Validate gap audit output status values."""

    def test_action_required_validates(self) -> None:
        output = GapAuditOutput(patient_id="bridge-demo-001", overall_status="ACTION_REQUIRED", items=[])
        assert output.overall_status == "ACTION_REQUIRED"

    def test_pass_validates(self) -> None:
        output = GapAuditOutput(patient_id="bridge-demo-001", overall_status="PASS", items=[])
        assert output.overall_status == "PASS"

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValidationError):
            GapAuditOutput(patient_id="bridge-demo-001", overall_status="PARTIAL", items=[])
