"""Determinism tests for golden patient outputs."""

from __future__ import annotations

from bridge_agent.tools.care_plan import generate_care_plan
from bridge_agent.tools.gap_audit import audit_documentation_gaps
from sentinel.tools.lace_plus import calculate_lace_plus
from sentinel.tools.risk_mapper import map_risk_drivers

EXPECTED_LACE_PLUS_SCORE = 14
EXPECTED_RISK_LEVEL = "HIGH"
EXPECTED_MEDICATION_FLAGS = {"warfarin", "furosemide"}
EXPECTED_SDOH_FLAG_PREFIXES = ["Z60", "Z59"]
EXPECTED_GAP_AUDIT_FAIL_COUNT = 3


class TestGoldenPatientDeterminism:
    """Ensure deterministic outputs for the golden patient bundle."""

    def test_lace_score_always_14(self, golden_patient_bundle) -> None:
        for _ in range(3):
            result = calculate_lace_plus(golden_patient_bundle)
            assert result["lace_plus_score"] == EXPECTED_LACE_PLUS_SCORE

    def test_risk_level_always_high(self, golden_patient_bundle) -> None:
        for _ in range(3):
            result = calculate_lace_plus(golden_patient_bundle)
            assert result["risk_level"].value == EXPECTED_RISK_LEVEL

    def test_medication_flags_always_include_warfarin_and_furosemide(self, golden_patient_bundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert EXPECTED_MEDICATION_FLAGS.issubset(set(risk_card.medication_flags))

    def test_sdoh_flags_always_include_z60_and_z59(self, golden_patient_bundle) -> None:
        risk_card = map_risk_drivers(golden_patient_bundle)
        assert any(flag.startswith("Z60") for flag in risk_card.sdoh_flags)
        assert any(flag.startswith("Z59") for flag in risk_card.sdoh_flags)

    def test_gap_audit_always_action_required(self, golden_risk_card, golden_patient_bundle) -> None:
        for _ in range(3):
            audit = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
            assert audit.overall_status == "ACTION_REQUIRED"

    def test_gap_audit_fail_count_stable(self, golden_risk_card, golden_patient_bundle) -> None:
        for _ in range(3):
            audit = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
            fail_count = sum(1 for item in audit.items if item.status == "FAIL")
            assert fail_count >= EXPECTED_GAP_AUDIT_FAIL_COUNT

    def test_care_plan_always_has_critical_action(self, golden_risk_card) -> None:
        for _ in range(3):
            plan = generate_care_plan(golden_risk_card)
            assert any(action.priority == "CRITICAL" for action in plan.actions)

    def test_care_plan_action_count_stable(self, golden_risk_card) -> None:
        counts = []
        for _ in range(3):
            plan = generate_care_plan(golden_risk_card)
            counts.append(len(plan.actions))
        assert counts[0] == counts[1] == counts[2]
