"""Integration tests for A2A discovery and request flow."""

from __future__ import annotations

import os

import httpx
import pytest
import respx

from bridge_agent.a2a_client import discover_sentinel, request_risk_assessment
from shared.models import RiskCard, RiskLevel, SHARPContext


@pytest.mark.asyncio
class TestDiscoverSentinel:
    """Validate marketplace discovery and fallback logic."""

    async def test_returns_marketplace_endpoint_on_success(self) -> None:
        with respx.mock(base_url=os.getenv("MARKETPLACE_URL", "https://app.promptopinion.ai/api/agents")) as router:
            router.get("/").respond(200, json={"endpoint_url": "https://custom-sentinel.example.com"})
            result = await discover_sentinel()
            assert result == "https://custom-sentinel.example.com"

    async def test_falls_back_to_env_url_on_failure(self) -> None:
        fallback = "http://localhost:8009"
        os.environ["SENTINEL_URL"] = fallback
        with respx.mock(base_url=os.getenv("MARKETPLACE_URL", "https://app.promptopinion.ai/api/agents")) as router:
            router.get("/").respond(500)
            result = await discover_sentinel()
            assert result == fallback

    async def test_falls_back_on_network_exception(self) -> None:
        fallback = os.getenv("SENTINEL_URL", "http://localhost:8001")
        with respx.mock(base_url=os.getenv("MARKETPLACE_URL", "https://app.promptopinion.ai/api/agents")) as router:
            router.get("/").mock(side_effect=httpx.ConnectError("boom"))
            result = await discover_sentinel()
            assert result == fallback


@pytest.mark.asyncio
class TestRequestRiskAssessment:
    """Validate A2A request/response parsing for RiskCard."""

    async def test_posts_to_correct_endpoint(self, sharp_context: SHARPContext) -> None:
        sentinel_url = "https://sentinel.example.com"
        os.environ["SENTINEL_URL"] = sentinel_url
        with respx.mock(base_url=sentinel_url) as router:
            route = router.post("/mcp/call").respond(200, json={"content": [{"type": "text", "text": RiskCard(
                patient_id="bridge-demo-001",
                lace_plus_score=1,
                risk_level=RiskLevel.LOW,
                primary_drivers=[],
                medication_flags=[],
                sdoh_flags=[],
                pending_labs=[],
                missing_follow_ups=[],
                fhir_citations=[],
            ).model_dump_json()}]})
            await request_risk_assessment(sharp_context)
            assert route.called

    async def test_passes_sharp_headers(self, sharp_context: SHARPContext) -> None:
        sentinel_url = "https://sentinel.example.com"
        os.environ["SENTINEL_URL"] = sentinel_url
        with respx.mock(base_url=sentinel_url) as router:
            router.post("/mcp/call").respond(200, json={"content": [{"type": "text", "text": RiskCard(
                patient_id="bridge-demo-001",
                lace_plus_score=1,
                risk_level=RiskLevel.LOW,
                primary_drivers=[],
                medication_flags=[],
                sdoh_flags=[],
                pending_labs=[],
                missing_follow_ups=[],
                fhir_citations=[],
            ).model_dump_json()}]})
            await request_risk_assessment(sharp_context)
            request = router.calls[0].request
            assert request.headers.get("x-sharp-patient-id") == sharp_context.patient_id

    async def test_parses_risk_card_from_response(self, sharp_context: SHARPContext) -> None:
        sentinel_url = "https://sentinel.example.com"
        os.environ["SENTINEL_URL"] = sentinel_url
        with respx.mock(base_url=sentinel_url) as router:
            router.post("/mcp/call").respond(
                200,
                json={"content": [{"type": "text", "text": RiskCard(
                    patient_id="bridge-demo-001",
                    lace_plus_score=1,
                    risk_level=RiskLevel.LOW,
                    primary_drivers=[],
                    medication_flags=[],
                    sdoh_flags=[],
                    pending_labs=[],
                    missing_follow_ups=[],
                    fhir_citations=[],
                ).model_dump_json()}]},
            )
            result = await request_risk_assessment(sharp_context)
            assert isinstance(result, RiskCard)
            assert result.patient_id == "bridge-demo-001"

    async def test_raises_on_non_200(self, sharp_context: SHARPContext) -> None:
        sentinel_url = "https://sentinel.example.com"
        os.environ["SENTINEL_URL"] = sentinel_url
        with respx.mock(base_url=sentinel_url) as router:
            router.post("/mcp/call").respond(500, json={"error": "boom"})
            with pytest.raises(Exception):
                await request_risk_assessment(sharp_context)

    async def test_raises_on_malformed_response(self, sharp_context: SHARPContext) -> None:
        sentinel_url = "https://sentinel.example.com"
        os.environ["SENTINEL_URL"] = sentinel_url
        with respx.mock(base_url=sentinel_url) as router:
            router.post("/mcp/call").respond(200, json={})
            with pytest.raises(Exception):
                await request_risk_assessment(sharp_context)
