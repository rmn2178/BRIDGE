"""End-to-end pipeline tests for SENTINEL and BRIDGE flow."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from bridge_agent import main as bridge_main
from bridge_agent.tools.care_plan import generate_care_plan
from bridge_agent.tools.gap_audit import audit_documentation_gaps
from bridge_agent.tools.pcp_handoff import draft_pcp_handoff
from sentinel import main as sentinel_main
from shared.models import CarePlanOutput, GapAuditOutput, PCPHandoff, RiskCard


class TestFullPipeline:
    """Validate full SENTINEL to BRIDGE pipeline with mocked FHIR access."""

    def test_sentinel_produces_valid_risk_card(self, monkeypatch, golden_patient_bundle, sharp_context) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        client = TestClient(sentinel_main.app)
        client.headers.update(
            {
                "x-sharp-patient-id": sharp_context.patient_id,
                "x-sharp-fhir-base-url": sharp_context.fhir_base_url,
                "x-sharp-access-token": sharp_context.access_token,
            }
        )
        response = client.post("/mcp/call", json={"name": "map_risk_drivers"})
        text = response.json()["content"][0]["text"]
        risk_card = RiskCard.model_validate_json(text)
        assert risk_card.lace_plus_score == 14
        assert risk_card.risk_level.value == "HIGH"
        assert "warfarin" in risk_card.medication_flags

    def test_bridge_care_plan_from_sentinel_risk_card(self, golden_risk_card: RiskCard) -> None:
        plan = generate_care_plan(golden_risk_card)
        assert any(action.priority == "CRITICAL" for action in plan.actions)
        assert plan.patient_instructions

    def test_bridge_gap_audit_from_sentinel_risk_card(self, golden_risk_card: RiskCard, golden_patient_bundle) -> None:
        audit = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        assert audit.overall_status == "ACTION_REQUIRED"
        assert len([item for item in audit.items if item.status == "FAIL"]) >= 3

    def test_bridge_pcp_handoff_from_sentinel_risk_card(self, golden_risk_card: RiskCard, golden_patient_bundle) -> None:
        handoff = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        assert len(handoff.handoff_letter) > 300
        assert "warfarin" in handoff.handoff_letter.lower() or "inr" in handoff.handoff_letter.lower()

    def test_full_bridge_api_pipeline(self, monkeypatch, golden_patient_bundle, sharp_context) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)

        sentinel_client = TestClient(sentinel_main.app)
        sentinel_client.headers.update(
            {
                "x-sharp-patient-id": sharp_context.patient_id,
                "x-sharp-fhir-base-url": sharp_context.fhir_base_url,
                "x-sharp-access-token": sharp_context.access_token,
            }
        )

        async def _call_sentinel(sharp):
            response = sentinel_client.post("/mcp/call", json={"name": "map_risk_drivers"})
            text = response.json()["content"][0]["text"]
            return RiskCard.model_validate_json(text)

        monkeypatch.setattr(bridge_main, "request_risk_assessment", _call_sentinel)

        bridge_client = TestClient(bridge_main.app)
        bridge_client.headers.update(
            {
                "x-sharp-patient-id": sharp_context.patient_id,
                "x-sharp-fhir-base-url": sharp_context.fhir_base_url,
                "x-sharp-access-token": sharp_context.access_token,
            }
        )

        response = bridge_client.post("/mcp/call", json={"name": "generate_care_plan"})
        assert response.status_code == 200
        text = response.json()["content"][0]["text"]
        plan = CarePlanOutput.model_validate_json(text)
        assert any(action.priority == "CRITICAL" for action in plan.actions)
