"""Integration tests for BRIDGE FastAPI MCP routes."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from bridge_agent import main as bridge_main
from shared.models import CarePlanOutput, GapAuditOutput, PCPHandoff


class TestBridgeToolsList:
    """Verify BRIDGE tool discovery endpoint."""

    def test_get_tools_returns_200(self, bridge_client: TestClient) -> None:
        response = bridge_client.get("/mcp/tools")
        assert response.status_code == 200

    def test_tools_list_has_4_tools(self, bridge_client: TestClient) -> None:
        response = bridge_client.get("/mcp/tools")
        assert len(response.json().get("tools", [])) == 4

    def test_tool_names_match_spec(self, bridge_client: TestClient) -> None:
        response = bridge_client.get("/mcp/tools")
        tool_names = {tool["name"] for tool in response.json().get("tools", [])}
        assert tool_names == {"generate_care_plan", "draft_pcp_handoff", "audit_documentation_gaps", "debate_discharge"}


class TestBridgeCarePlan:
    """Verify care plan tool behavior for golden risk card."""

    def test_generate_care_plan_returns_200(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "generate_care_plan"})
        assert response.status_code == 200

    def test_response_is_mcp_envelope(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "generate_care_plan"})
        body = response.json()
        assert "content" in body
        assert body["content"][0]["type"] == "text"
        assert body["content"][0]["text"]

    def test_care_plan_has_actions(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "generate_care_plan"})
        text = response.json()["content"][0]["text"]
        data = json.loads(text)
        plan = CarePlanOutput.model_validate(data["care_plan"])
        assert len(plan.actions) >= 1

    def test_critical_action_present(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "generate_care_plan"})
        text = response.json()["content"][0]["text"]
        data = json.loads(text)
        plan = CarePlanOutput.model_validate(data["care_plan"])
        assert any(action.priority == "CRITICAL" for action in plan.actions)


class TestBridgePCPHandoff:
    """Verify PCP handoff output from BRIDGE."""

    def test_draft_pcp_handoff_returns_200(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "draft_pcp_handoff"})
        assert response.status_code == 200

    def test_handoff_letter_non_empty(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "draft_pcp_handoff"})
        text = response.json()["content"][0]["text"]
        handoff = PCPHandoff.model_validate_json(text)
        assert len(handoff.handoff_letter) > 100


class TestBridgeGapAudit:
    """Verify gap audit output from BRIDGE."""

    def test_gap_audit_returns_200(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "audit_documentation_gaps"})
        assert response.status_code == 200

    def test_overall_status_action_required(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "audit_documentation_gaps"})
        text = response.json()["content"][0]["text"]
        audit = GapAuditOutput.model_validate_json(text)
        assert audit.overall_status == "ACTION_REQUIRED"

    def test_fail_items_present(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "audit_documentation_gaps"})
        text = response.json()["content"][0]["text"]
        audit = GapAuditOutput.model_validate_json(text)
        assert len([item for item in audit.items if item.status == "FAIL"]) >= 2


class TestBridgeErrorHandling:
    """Verify BRIDGE error behavior for A2A and unknown tool cases."""

    def test_a2a_failure_returns_503(self, bridge_client: TestClient, monkeypatch) -> None:
        async def _fail_request(_: object):
            raise Exception("A2A failure")

        monkeypatch.setattr(bridge_main, "request_risk_assessment", _fail_request)
        response = bridge_client.post("/mcp/call", json={"name": "generate_care_plan"})
        assert response.status_code == 503

    def test_unknown_tool_returns_404(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": "does_not_exist"})
        assert response.status_code == 404
