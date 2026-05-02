"""A2A client for discovering and calling SENTINEL."""

from __future__ import annotations

import os

import httpx
from fastapi import HTTPException

from shared.models import RiskCard, SHARPContext

SENTINEL_AGENT_URL = os.getenv("SENTINEL_URL", "http://localhost:8001")
MARKETPLACE_REGISTRY = os.getenv(
    "MARKETPLACE_URL", "https://app.promptopinion.ai/api/agents"
)


def _sentinel_fallback_url() -> str:
    return os.getenv("SENTINEL_URL", SENTINEL_AGENT_URL)


def _marketplace_url_explicit() -> bool:
    return "MARKETPLACE_URL" in os.environ


async def discover_sentinel() -> str:
    """Discover SENTINEL via the marketplace registry with safe fallback."""

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                MARKETPLACE_REGISTRY, params={"name": "sentinel-risk-stratifier"}
            )
        if response.status_code == 200:
            payload = response.json()
            endpoint_url = payload.get("endpoint_url")
            if isinstance(endpoint_url, str) and endpoint_url.strip():
                return endpoint_url.strip()
    except Exception:
        return _sentinel_fallback_url()
    return _sentinel_fallback_url()


async def request_risk_assessment(sharp: SHARPContext) -> RiskCard:
    """Request a RiskCard from the SENTINEL MCP endpoint."""

    if _marketplace_url_explicit():
        sentinel_url = await discover_sentinel()
    else:
        sentinel_url = _sentinel_fallback_url()
    headers = {
        "x-sharp-patient-id": sharp.patient_id,
        "x-sharp-fhir-base-url": sharp.fhir_base_url,
        "x-sharp-access-token": sharp.access_token,
        "Content-Type": "application/json",
    }
    payload = {"name": "map_risk_drivers", "arguments": {}}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(f"{sentinel_url}/mcp/call", json=payload, headers=headers)

    if response.status_code // 100 != 2:
        raise HTTPException(
            status_code=503,
            detail=f"SENTINEL error: {response.status_code}",
        )

    data = response.json()
    try:
        text = data["content"][0]["text"]
        return RiskCard.model_validate_json(text)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to parse SENTINEL response: {exc}",
        )
