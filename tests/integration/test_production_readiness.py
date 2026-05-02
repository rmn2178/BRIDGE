"""Tests for production-readiness features: health, JSON-RPC 2.0, SSE, SMART scopes, Agent Cards."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import jwt
import pytest
from fastapi.testclient import TestClient

from bridge_agent import main as bridge_main
from sentinel import main as sentinel_main
from shared.security import validate_smart_scopes
from common.settings import refresh_settings


# ── Fix 1: Health endpoints ───────────────────────────────────────────────────

class TestHealthEndpoints:
    def test_sentinel_health_returns_200(self) -> None:
        client = TestClient(sentinel_main.app)
        response = client.get("/health")
        assert response.status_code == 200

    def test_sentinel_health_body(self) -> None:
        client = TestClient(sentinel_main.app)
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["service"] == "sentinel"

    def test_bridge_health_returns_200(self) -> None:
        client = TestClient(bridge_main.app)
        response = client.get("/health")
        assert response.status_code == 200

    def test_bridge_health_body(self) -> None:
        client = TestClient(bridge_main.app)
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["service"] == "bridge"

    def test_health_bypasses_auth(self, monkeypatch) -> None:
        monkeypatch.setenv("AUTH_REQUIRED", "true")
        refresh_settings()
        try:
            client = TestClient(sentinel_main.app)
            response = client.get("/health")
            assert response.status_code == 200
        finally:
            monkeypatch.delenv("AUTH_REQUIRED", raising=False)
            refresh_settings()

    def test_health_not_rate_limited(self, sentinel_client: TestClient) -> None:
        for _ in range(5):
            assert sentinel_client.get("/health").status_code == 200


# ── Fix 2: JSON-RPC 2.0 ──────────────────────────────────────────────────────

class TestJsonRpc20Sentinel:
    def test_plain_call_returns_plain_envelope(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={"name": "fhir_discharge_snapshot"})
        body = response.json()
        assert "jsonrpc" not in body
        assert "content" in body

    def test_jsonrpc_call_returns_jsonrpc_envelope(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={
            "jsonrpc": "2.0", "id": 42,
            "method": "tools/call",
            "params": {"name": "fhir_discharge_snapshot"},
        })
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 42
        assert "result" in body
        assert "content" in body["result"]

    def test_jsonrpc_unknown_tool_returns_error_object(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool"},
        })
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert "error" in body
        assert body["error"]["code"] == -32601

    def test_jsonrpc_result_text_is_valid_json(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.post("/mcp/call", json={
            "jsonrpc": "2.0", "id": 7,
            "method": "tools/call",
            "params": {"name": "map_risk_drivers"},
        })
        text = response.json()["result"]["content"][0]["text"]
        json.loads(text)


class TestJsonRpc20Bridge:
    def test_jsonrpc_care_plan_returns_envelope(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={
            "jsonrpc": "2.0", "id": 99,
            "method": "tools/call",
            "params": {"name": "generate_care_plan"},
        })
        body = response.json()
        assert body["jsonrpc"] == "2.0"
        assert body["id"] == 99
        assert "result" in body

    def test_jsonrpc_unknown_tool_returns_error_object(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.post("/mcp/call", json={
            "jsonrpc": "2.0", "id": 5,
            "method": "tools/call",
            "params": {"name": "nonexistent"},
        })
        body = response.json()
        assert "error" in body
        assert body["error"]["code"] == -32601


# ── Fix 3: SSE streaming ──────────────────────────────────────────────────────

class TestSseStreamingSentinel:
    def test_stream_returns_200(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/map_risk_drivers")
        assert response.status_code == 200

    def test_stream_content_type_is_sse(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/map_risk_drivers")
        assert "text/event-stream" in response.headers["content-type"]

    def test_stream_contains_result_event(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/map_risk_drivers")
        assert "event: result" in response.text

    def test_stream_contains_done_event(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/map_risk_drivers")
        assert "event: done" in response.text

    def test_stream_contains_progress_events(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/map_risk_drivers")
        assert "event: progress" in response.text

    def test_stream_result_is_valid_risk_card(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        from shared.models import RiskCard
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/map_risk_drivers")
        result_line = next(l for l in response.text.splitlines() if l.startswith("data:") and "lace_plus_score" in l)
        RiskCard.model_validate_json(result_line[len("data:"):].strip())

    def test_stream_lace_plus_tool(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/calculate_lace_plus")
        assert "event: result" in response.text

    def test_stream_unknown_tool_returns_error_event(self, sentinel_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(sentinel_main, "build_patient_bundle", _mock_bundle)
        response = sentinel_client.get("/mcp/stream/nonexistent_tool")
        assert "event: error" in response.text

    def test_stream_missing_patient_id_returns_400(self) -> None:
        client = TestClient(sentinel_main.app)
        response = client.get("/mcp/stream/map_risk_drivers")
        assert response.status_code == 400


class TestSseStreamingBridge:
    def test_stream_care_plan_returns_200(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.get("/mcp/stream/generate_care_plan")
        assert response.status_code == 200

    def test_stream_care_plan_has_result(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.get("/mcp/stream/generate_care_plan")
        assert "event: result" in response.text

    def test_stream_care_plan_sentinel_progress_event(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.get("/mcp/stream/generate_care_plan")
        assert "sentinel_a2a" in response.text

    def test_stream_gap_audit_has_result(self, bridge_client: TestClient, monkeypatch, golden_patient_bundle) -> None:
        async def _mock_bundle(_): return golden_patient_bundle
        monkeypatch.setattr(bridge_main, "build_patient_bundle", _mock_bundle)
        response = bridge_client.get("/mcp/stream/audit_documentation_gaps")
        assert "event: result" in response.text


# ── Fix 4: SMART-on-FHIR OAuth scope validation ───────────────────────────────

def _make_token(scopes: str) -> str:
    return jwt.encode({"sub": "test", "scope": scopes}, "secret", algorithm="HS256")


class TestSmartScopeValidation:
    def test_no_required_scopes_always_passes(self) -> None:
        validate_smart_scopes("")
        validate_smart_scopes("some_token")

    def test_valid_scopes_pass(self, monkeypatch) -> None:
        monkeypatch.setenv("SMART_REQUIRED_SCOPES", "patient/*.read")
        refresh_settings()
        try:
            token = _make_token("patient/*.read launch/patient")
            validate_smart_scopes(token)
        finally:
            monkeypatch.delenv("SMART_REQUIRED_SCOPES", raising=False)
            refresh_settings()

    def test_missing_scope_raises_403(self, monkeypatch) -> None:
        from fastapi import HTTPException
        monkeypatch.setenv("SMART_REQUIRED_SCOPES", "patient/*.read")
        refresh_settings()
        try:
            token = _make_token("launch/patient")
            with pytest.raises(HTTPException) as exc_info:
                validate_smart_scopes(token)
            assert exc_info.value.status_code == 403
            assert "patient/*.read" in exc_info.value.detail
        finally:
            monkeypatch.delenv("SMART_REQUIRED_SCOPES", raising=False)
            refresh_settings()

    def test_invalid_token_raises_401(self, monkeypatch) -> None:
        from fastapi import HTTPException
        monkeypatch.setenv("SMART_REQUIRED_SCOPES", "patient/*.read")
        refresh_settings()
        try:
            with pytest.raises(HTTPException) as exc_info:
                validate_smart_scopes("not.a.jwt")
            assert exc_info.value.status_code == 401
        finally:
            monkeypatch.delenv("SMART_REQUIRED_SCOPES", raising=False)
            refresh_settings()

    def test_multiple_required_scopes_all_must_be_present(self, monkeypatch) -> None:
        from fastapi import HTTPException
        monkeypatch.setenv("SMART_REQUIRED_SCOPES", "patient/*.read,patient/*.write")
        refresh_settings()
        try:
            token = _make_token("patient/*.read")
            with pytest.raises(HTTPException) as exc_info:
                validate_smart_scopes(token)
            assert "patient/*.write" in exc_info.value.detail
        finally:
            monkeypatch.delenv("SMART_REQUIRED_SCOPES", raising=False)
            refresh_settings()

    def test_empty_access_token_skips_check_when_scopes_required(self, monkeypatch) -> None:
        monkeypatch.setenv("SMART_REQUIRED_SCOPES", "patient/*.read")
        refresh_settings()
        try:
            validate_smart_scopes("")  # empty token → skip, no raise
        finally:
            monkeypatch.delenv("SMART_REQUIRED_SCOPES", raising=False)
            refresh_settings()


# ── Fix 5: Agent Card completeness ───────────────────────────────────────────

class TestAgentCards:
    def _load(self, name: str) -> dict:
        path = Path(__file__).resolve().parents[2] / "manifests" / name
        return json.loads(path.read_text())

    def test_sentinel_card_has_required_fields(self) -> None:
        card = self._load("sentinel_manifest.json")
        for field in ("name", "version", "protocol", "jsonrpc", "endpoint", "health_check",
                      "auth_schemes", "sharp_enabled", "sharp_headers", "capabilities", "tools"):
            assert field in card, f"Missing field: {field}"

    def test_bridge_card_has_required_fields(self) -> None:
        card = self._load("bridge_manifest.json")
        for field in ("name", "version", "protocol", "jsonrpc", "endpoint", "health_check",
                      "auth_schemes", "sharp_enabled", "sharp_headers", "capabilities", "tools",
                      "a2a_dependencies"):
            assert field in card, f"Missing field: {field}"

    def test_sentinel_jsonrpc_version(self) -> None:
        assert self._load("sentinel_manifest.json")["jsonrpc"] == "2.0"

    def test_bridge_jsonrpc_version(self) -> None:
        assert self._load("bridge_manifest.json")["jsonrpc"] == "2.0"

    def test_bridge_declares_sentinel_dependency(self) -> None:
        card = self._load("bridge_manifest.json")
        assert "sentinel-risk-stratifier" in card["a2a_dependencies"]

    def test_sentinel_tools_have_input_schema(self) -> None:
        card = self._load("sentinel_manifest.json")
        for tool in card["tools"]:
            assert "input_schema" in tool, f"Tool {tool['name']} missing input_schema"

    def test_bridge_tools_have_input_schema(self) -> None:
        card = self._load("bridge_manifest.json")
        for tool in card["tools"]:
            assert "input_schema" in tool, f"Tool {tool['name']} missing input_schema"

    def test_both_cards_declare_sharp_enabled(self) -> None:
        assert self._load("sentinel_manifest.json")["sharp_enabled"] is True
        assert self._load("bridge_manifest.json")["sharp_enabled"] is True

    def test_both_cards_have_stream_endpoint(self) -> None:
        assert "stream_endpoint" in self._load("sentinel_manifest.json")
        assert "stream_endpoint" in self._load("bridge_manifest.json")

    def test_both_cards_have_auth_schemes(self) -> None:
        for name in ("sentinel_manifest.json", "bridge_manifest.json"):
            card = self._load(name)
            assert len(card["auth_schemes"]) >= 2

    def test_both_cards_declare_synthetic_data(self) -> None:
        for name in ("sentinel_manifest.json", "bridge_manifest.json"):
            assert self._load(name)["data_usage"] == "synthetic_only"


# ── Live /agent-card endpoints ────────────────────────────────────────────────

class TestLiveAgentCard:
    def test_sentinel_agent_card_returns_200(self) -> None:
        client = TestClient(sentinel_main.app)
        assert client.get("/agent-card").status_code == 200

    def test_sentinel_agent_card_has_call_url(self) -> None:
        client = TestClient(sentinel_main.app)
        card = client.get("/agent-card").json()
        assert "call_url" in card
        assert "/mcp/call" in card["call_url"]

    def test_sentinel_agent_card_data_usage_synthetic(self) -> None:
        client = TestClient(sentinel_main.app)
        assert client.get("/agent-card").json()["data_usage"] == "synthetic_only"

    def test_sentinel_agent_card_no_phi_compliance(self) -> None:
        client = TestClient(sentinel_main.app)
        assert "no_real_PHI" in client.get("/agent-card").json()["compliance"]

    def test_sentinel_root_redirects_to_agent_card(self) -> None:
        client = TestClient(sentinel_main.app, follow_redirects=False)
        response = client.get("/")
        assert response.status_code in (301, 302, 307, 308)
        assert "/agent-card" in response.headers["location"]

    def test_bridge_agent_card_returns_200(self) -> None:
        client = TestClient(bridge_main.app)
        assert client.get("/agent-card").status_code == 200

    def test_bridge_agent_card_has_sentinel_dependency(self) -> None:
        client = TestClient(bridge_main.app)
        card = client.get("/agent-card").json()
        deps = [d["name"] if isinstance(d, dict) else d for d in card["a2a_dependencies"]]
        assert "sentinel-risk-stratifier" in deps

    def test_bridge_agent_card_data_usage_synthetic(self) -> None:
        client = TestClient(bridge_main.app)
        assert client.get("/agent-card").json()["data_usage"] == "synthetic_only"

    def test_bridge_agent_card_no_phi_compliance(self) -> None:
        client = TestClient(bridge_main.app)
        assert "no_real_PHI" in client.get("/agent-card").json()["compliance"]

    def test_bridge_root_redirects_to_agent_card(self) -> None:
        client = TestClient(bridge_main.app, follow_redirects=False)
        response = client.get("/")
        assert response.status_code in (301, 302, 307, 308)
        assert "/agent-card" in response.headers["location"]

    def test_sentinel_agent_card_tools_match_mcp_tools(self) -> None:
        client = TestClient(sentinel_main.app)
        card_tools = {t["name"] for t in client.get("/agent-card").json()["tools"]}
        mcp_tools = {t["name"] for t in client.get("/mcp/tools").json()["tools"]}
        assert card_tools == mcp_tools

    def test_bridge_agent_card_tools_match_mcp_tools(self) -> None:
        client = TestClient(bridge_main.app)
        card_tools = {t["name"] for t in client.get("/agent-card").json()["tools"]}
        mcp_tools = {t["name"] for t in client.get("/mcp/tools").json()["tools"]}
        assert card_tools == mcp_tools
