"""Unit tests for care plan action generation logic."""

from __future__ import annotations

from bridge_agent.tools.care_plan import generate_care_plan
from shared.models import CarePlanOutput, RiskCard


class TestCarePlanGoldenPatient:
    """Validate care plan actions for the golden patient risk card."""

    def test_returns_care_plan_output_type(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        assert isinstance(result, CarePlanOutput)

    def test_has_at_least_4_actions(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        assert len(result.actions) >= 4

    def test_warfarin_produces_critical_action(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        critical_actions = [a for a in result.actions if a.priority == "CRITICAL"]
        assert critical_actions
        assert any("inr" in a.action.lower() or "warfarin" in a.action.lower() for a in critical_actions)

    def test_chf_produces_weight_monitoring_action(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        weight_actions = [a for a in result.actions if "weight" in a.action.lower()]
        assert weight_actions
        assert all(a.priority == "HIGH" for a in weight_actions)

    def test_missing_followup_produces_high_action(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        assert any(a.risk_card_source == "missing_follow_ups" for a in result.actions)

    def test_living_alone_produces_home_health_action(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        assert any(
            "home health" in a.action.lower() or "nursing" in a.action.lower()
            for a in result.actions
        )

    def test_patient_instructions_not_empty(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        assert isinstance(result.patient_instructions, str)
        assert len(result.patient_instructions) > 50

    def test_patient_instructions_no_jargon(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        forbidden = ["INR", "anticoagulation", "diuresis", "LACE", "cardiomegaly"]
        assert not any(term.lower() in result.patient_instructions.lower() for term in forbidden)

    def test_clinician_summary_contains_lace_score(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        assert str(golden_risk_card.lace_plus_score) in result.clinician_summary

    def test_all_actions_have_rationale(self, golden_risk_card: RiskCard) -> None:
        result = generate_care_plan(golden_risk_card)
        assert all(a.rationale and a.rationale.strip() for a in result.actions)


class TestCarePlanMinimalRiskCard:
    """Validate care plan behavior for low-risk inputs."""

    def test_minimal_card_no_critical_actions(self, minimal_risk_card: RiskCard) -> None:
        result = generate_care_plan(minimal_risk_card)
        assert not any(a.priority == "CRITICAL" for a in result.actions)

    def test_minimal_card_returns_valid_output(self, minimal_risk_card: RiskCard) -> None:
        result = generate_care_plan(minimal_risk_card)
        assert isinstance(result, CarePlanOutput)
