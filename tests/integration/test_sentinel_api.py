"""Integration tests for SENTINEL FastAPI MCP routes."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from sentinel import main as sentinel_main


class TestSentinelToolsList:
    """Verify tool discovery endpoint for SENTINEL."""

    def test_get_tools_returns_200(self, sentinel_client: TestClient) -> None:
        response = sentinel_client.get("/mcp/tools")
        assert response.status_code == 200

    def test_tools_list_has_3_tools(self, sentinel_client: TestClient) -> None:
        response = sentinel_client.get("/mcp/tools")
        assert len(response.json().get("tools", [])) == 3

    def test_tool_names_match_spec(self, sentinel_client: TestClient) -> None:
        response = sentinel_client.get("/mcp/tools")
        tool_names = {tool["name"] for tool in response.json().get("tools", [])}
        assert tool_names == {"fhir_discharge_snapshot", "calculate_lace_plus", "map_risk_drivers"}


class TestSentinelFhirSnapshot:
    """Verify MCP envelope and JSON validity for FHIR snapshot tool."""

    def test_fhir_snapshot_returns_200(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "fhir_discharge_snapshot"})
        assert response.status_code == 200

    def test_response_is_mcp_envelope(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "fhir_discharge_snapshot"})
        body = response.json()
        assert "content" in body
        assert body["content"][0]["type"] == "text"
        assert body["content"][0]["text"]

    def test_fhir_snapshot_text_is_valid_json(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "fhir_discharge_snapshot"})
        payload = response.json()["content"][0]["text"]
        json.loads(payload)


class TestSentinelLacePlus:
    """Verify LACE+ tool output for golden patient."""

    def test_lace_plus_returns_200(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "calculate_lace_plus"})
        assert response.status_code == 200

    def test_lace_score_is_integer_in_response(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "calculate_lace_plus"})
        payload = json.loads(response.json()["content"][0]["text"])
        assert isinstance(payload["lace_plus_score"], int)

    def test_lace_score_equals_14_for_golden_patient(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "calculate_lace_plus"})
        payload = json.loads(response.json()["content"][0]["text"])
        assert payload["lace_plus_score"] == 14


class TestSentinelRiskMapper:
    """Verify RiskCard output for golden patient."""

    def test_risk_mapper_returns_200(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "map_risk_drivers"})
        assert response.status_code == 200

    def test_risk_card_schema_valid(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        from shared.models import RiskCard

        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "map_risk_drivers"})
        text = response.json()["content"][0]["text"]
        RiskCard.model_validate_json(text)

    def test_warfarin_in_medication_flags(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        from shared.models import RiskCard

        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "map_risk_drivers"})
        text = response.json()["content"][0]["text"]
        risk_card = RiskCard.model_validate_json(text)
        assert "warfarin" in risk_card.medication_flags


class TestSentinelErrorHandling:
    """Verify SENTINEL error responses for invalid requests."""

    def test_missing_patient_id_returns_400(self) -> None:
        client = TestClient(sentinel_main.app)
        response = client.post("/mcp/call", json={"name": "map_risk_drivers"})
        assert response.status_code == 400

    def test_unknown_tool_returns_404(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "does_not_exist"})
        assert response.status_code == 404
