"""Contract tests for MCP response envelope schema."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from bridge_agent import main as bridge_main
from sentinel import main as sentinel_main

SENTINEL_TOOL_NAMES = [
    "fhir_discharge_snapshot",
    "calculate_lace_plus",
    "map_risk_drivers",
]

BRIDGE_TOOL_NAMES = [
    "generate_care_plan",
    "draft_pcp_handoff",
    "audit_documentation_gaps",
]


def _assert_envelope(response_json: dict) -> None:
    assert "content" in response_json
    assert isinstance(response_json["content"], list)
    assert response_json["content"][0]["type"] == "text"
    assert isinstance(response_json["content"][0]["text"], str)
    assert response_json["content"][0]["text"]
    json.loads(response_json["content"][0]["text"])


@pytest.mark.parametrize("tool_name", SENTINEL_TOOL_NAMES)
class TestSentinelMcpEnvelope:
    """Validate MCP envelopes for all SENTINEL tools."""

    def test_mcp_envelope_schema(self, tool_name: str, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": tool_name})
        _assert_envelope(response.json())


@pytest.mark.parametrize("tool_name", BRIDGE_TOOL_NAMES)
class TestBridgeMcpEnvelope:
    """Validate MCP envelopes for all BRIDGE tools."""

    def test_mcp_envelope_schema(self, tool_name: str, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_):
            return golden_patient_bundle

        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={"name": tool_name})
        _assert_envelope(response.json())
