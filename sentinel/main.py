"""FastAPI MCP server for the SENTINEL risk stratifier."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import httpx
from pydantic import BaseModel, Field

from shared.sharp import parse_sharp_context
from shared.security import audit_log, enforce_rate_limit, get_user_identity
from shared.cache import TTLCache, RedisCache, create_redis_client
from sentinel.tools.fhir_snapshot import configure_fhir_client
from sentinel.tools.fhir_snapshot import build_patient_bundle
from sentinel.tools.lace_plus import calculate_lace_plus
from sentinel.tools.risk_mapper import map_risk_drivers
from starlette.responses import JSONResponse
import structlog

from common.logging import configure_logging, correlation_middleware

_tool_cache = TTLCache(ttl_seconds=int(os.getenv("TOOLS_CACHE_TTL_SECONDS", "300")))
_risk_cache = TTLCache(ttl_seconds=int(os.getenv("RISK_CACHE_TTL_SECONDS", "300")))
_logger = structlog.get_logger("sentinel")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    limits = httpx.Limits(
        max_connections=int(os.getenv("HTTP_MAX_CONNECTIONS", "100")),
        max_keepalive_connections=int(os.getenv("HTTP_MAX_KEEPALIVE", "20")),
    )
    timeout = httpx.Timeout(20.0)
    client = httpx.AsyncClient(limits=limits, timeout=timeout)
    redis_client = await create_redis_client()
    redis_cache = RedisCache(redis_client)
    configure_fhir_client(client, redis_cache)
    yield
    await client.aclose()
    if redis_client:
        await redis_client.aclose()


app = FastAPI(title="SENTINEL MCP", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOW_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=os.getenv("CORS_ALLOW_METHODS", "*").split(","),
    allow_headers=os.getenv("CORS_ALLOW_HEADERS", "*").split(","),
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.middleware("http")(correlation_middleware(_logger))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = os.getenv(
        "CSP_POLICY", "default-src 'none'"
    )
    if os.getenv("HSTS_ENABLED", "true").lower() == "true":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


class MCPCall(BaseModel):
    """MCP tool invocation request payload."""

    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


def _mcp_envelope(payload: str) -> dict:
    return {"content": [{"type": "text", "text": payload}]}


tools = [
    {
        "name": "fhir_discharge_snapshot",
        "description": "Fetch patient-centered FHIR snapshot for discharge.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "calculate_lace_plus",
        "description": "Calculate deterministic LACE+ score and drivers.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "map_risk_drivers",
        "description": "Map clinical drivers into a structured RiskCard.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


@app.get("/mcp/tools")
async def list_tools(request: Request) -> dict:
    """Expose MCP tool definitions."""
    user_id = await get_user_identity(request)
    enforce_rate_limit(request, request.headers.get("x-sharp-patient-id", ""))
    audit_log(request, request.headers.get("x-sharp-patient-id", ""), user_id, "list_tools")
    cached = _tool_cache.get("tools")
    if cached:
        return cached
    response = {"tools": tools}
    _tool_cache.set("tools", response)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.post("/mcp/call")
async def call_tool(request: Request, call: MCPCall) -> dict:
    """Dispatch MCP tool requests to SENTINEL tooling."""

    sharp = parse_sharp_context(request)
    if not sharp.patient_id:
        raise HTTPException(status_code=400, detail="Missing SHARP patient_id")

    user_id = await get_user_identity(request)
    enforce_rate_limit(request, sharp.patient_id)
    audit_log(request, sharp.patient_id, user_id, call.name)
    _logger.info(
        "tool_call",
        tool=call.name,
        patient_id=sharp.patient_id,
        correlation_id=getattr(request.state, "correlation_id", None),
    )

    if call.name == "map_risk_drivers":
        risk_cache_key = f"risk:{sharp.fhir_base_url}:{sharp.patient_id}"
        cached = _risk_cache.get(risk_cache_key)
        if cached:
            return _mcp_envelope(cached.model_dump_json())

    bundle = await build_patient_bundle(sharp)

    if call.name == "fhir_discharge_snapshot":
        return _mcp_envelope(bundle.model_dump_json())
    if call.name == "calculate_lace_plus":
        lace = calculate_lace_plus(bundle)
        payload = dict(lace)
        if hasattr(payload.get("risk_level"), "value"):
            payload["risk_level"] = payload["risk_level"].value
        return _mcp_envelope(json.dumps(payload, default=str))
    if call.name == "map_risk_drivers":
        risk_card = map_risk_drivers(bundle)
        risk_cache_key = f"risk:{sharp.fhir_base_url}:{sharp.patient_id}"
        _risk_cache.set(risk_cache_key, risk_card)
        return _mcp_envelope(risk_card.model_dump_json())

    raise HTTPException(status_code=404, detail="Unknown tool name")
