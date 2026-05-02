"""FastAPI MCP server for the SENTINEL risk stratifier."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
import httpx
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
import structlog

from common.logging import configure_logging, correlation_middleware
from sentinel.tools.fhir_snapshot import configure_fhir_client, build_patient_bundle
from sentinel.tools.lace_plus import calculate_lace_plus
from sentinel.tools.risk_mapper import map_risk_drivers
from shared.cache import TTLCache, RedisCache, create_redis_client
from shared.security import audit_log, enforce_rate_limit, get_user_identity, validate_smart_scopes
from shared.sharp import parse_sharp_context

_tool_cache = TTLCache(ttl_seconds=int(os.getenv("TOOLS_CACHE_TTL_SECONDS", "300")))
_risk_cache = TTLCache(ttl_seconds=int(os.getenv("RISK_CACHE_TTL_SECONDS", "300")))
_logger = structlog.get_logger("sentinel")

_TOOLS = [
    {
        "name": "fhir_discharge_snapshot",
        "description": "Fetch patient-centered FHIR snapshot for discharge.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "calculate_lace_plus",
        "description": "Calculate deterministic LACE+ readmission risk score and drivers.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "map_risk_drivers",
        "description": "Map clinical drivers into a structured RiskCard with FHIR citations.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    limits = httpx.Limits(
        max_connections=int(os.getenv("HTTP_MAX_CONNECTIONS", "100")),
        max_keepalive_connections=int(os.getenv("HTTP_MAX_KEEPALIVE", "20")),
    )
    client = httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(20.0))
    redis_client = await create_redis_client()
    configure_fhir_client(client, RedisCache(redis_client))
    yield
    await client.aclose()
    if redis_client:
        await redis_client.aclose()


app = FastAPI(title="SENTINEL MCP", version="1.0.0", lifespan=lifespan)

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
    response.headers["Content-Security-Policy"] = os.getenv("CSP_POLICY", "default-src 'none'")
    if os.getenv("HSTS_ENABLED", "true").lower() == "true":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── JSON-RPC 2.0 helpers ──────────────────────────────────────────────────────

class MCPCall(BaseModel):
    """MCP tool invocation — accepts both plain and JSON-RPC 2.0 shaped bodies."""
    name: str = ""
    arguments: Dict[str, Any] = Field(default_factory=dict)
    jsonrpc: Optional[str] = None
    id: Optional[Any] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


def _rpc_result(payload: str, rpc_id: Any) -> dict:
    envelope = {"content": [{"type": "text", "text": payload}]}
    if rpc_id is not None:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": envelope}
    return envelope


def _resolve_tool_name(call: MCPCall) -> str:
    if call.method == "tools/call" and call.params:
        return call.params.get("name", call.name)
    return call.name


# ── Health & Discovery ───────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok", "service": "sentinel"}


@app.get("/agent-card")
async def agent_card() -> dict:
    """Prompt Opinion marketplace discovery endpoint."""
    base = os.getenv("SENTINEL_URL", "http://localhost:8001")
    return {
        "name": "sentinel-risk-stratifier",
        "display_name": "SENTINEL Risk Stratifier",
        "description": (
            "Deterministic discharge risk stratifier using LACE+ scoring and live FHIR R4 "
            "snapshots. Produces a structured RiskCard with clinical drivers, medication "
            "flags, SDoH flags, and FHIR citations."
        ),
        "version": "1.0.0",
        "protocol": "mcp",
        "jsonrpc": "2.0",
        "endpoint": f"{base}/mcp",
        "call_url": f"{base}/mcp/call",
        "tools_url": f"{base}/mcp/tools",
        "health_check": f"{base}/health",
        "stream_endpoint": f"{base}/mcp/stream/{{tool_name}}",
        "auth_schemes": [
            {"type": "bearer", "description": "SMART-on-FHIR OAuth 2.0 via x-sharp-access-token"},
            {"type": "api_key", "header": "x-api-key"},
        ],
        "sharp_enabled": True,
        "sharp_headers": [
            "x-sharp-patient-id",
            "x-sharp-fhir-base-url",
            "x-sharp-access-token",
            "x-sharp-encounter-id",
            "x-sharp-practitioner-id",
        ],
        "capabilities": [
            "fhir_r4", "lace_plus_scoring", "risk_stratification",
            "sse_streaming", "audit_trail",
        ],
        "fhir_resources": [
            "Patient", "Condition", "MedicationRequest", "Observation",
            "Encounter", "AllergyIntolerance", "Appointment",
        ],
        "tools": _TOOLS,
        "a2a_dependencies": [],
        "data_usage": "synthetic_only",
        "compliance": ["HIPAA_audit_log", "SSRF_protected", "rate_limited", "no_real_PHI"],
    }


@app.get("/", include_in_schema=False)
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/agent-card")


# ── Tool discovery ────────────────────────────────────────────────────────────

@app.get("/mcp/tools")
async def list_tools(request: Request) -> dict:
    user_id = await get_user_identity(request)
    enforce_rate_limit(request, request.headers.get("x-sharp-patient-id", ""))
    audit_log(request, request.headers.get("x-sharp-patient-id", ""), user_id, "list_tools")
    cached = _tool_cache.get("tools")
    if cached:
        return cached
    response = {"tools": _TOOLS}
    _tool_cache.set("tools", response)
    return response


# ── Tool execution ────────────────────────────────────────────────────────────

@app.post("/mcp/call")
async def call_tool(request: Request, call: MCPCall) -> dict:
    sharp = parse_sharp_context(request)
    if not sharp.patient_id:
        raise HTTPException(status_code=400, detail="Missing SHARP patient_id")

    validate_smart_scopes(sharp.access_token)
    user_id = await get_user_identity(request)
    enforce_rate_limit(request, sharp.patient_id)
    audit_log(request, sharp.patient_id, user_id, call.name)
    _logger.info(
        "tool_call",
        tool=call.name,
        patient_id=sharp.patient_id,
        correlation_id=getattr(request.state, "correlation_id", None),
    )

    tool_name = _resolve_tool_name(call)
    rpc_id = call.id

    if tool_name == "map_risk_drivers":
        risk_cache_key = f"risk:{sharp.fhir_base_url}:{sharp.patient_id}"
        cached = _risk_cache.get(risk_cache_key)
        if cached:
            return _rpc_result(cached.model_dump_json(), rpc_id)

    bundle = await build_patient_bundle(sharp)

    if tool_name == "fhir_discharge_snapshot":
        return _rpc_result(bundle.model_dump_json(), rpc_id)

    if tool_name == "calculate_lace_plus":
        lace = calculate_lace_plus(bundle)
        payload = dict(lace)
        if hasattr(payload.get("risk_level"), "value"):
            payload["risk_level"] = payload["risk_level"].value
        return _rpc_result(json.dumps(payload, default=str), rpc_id)

    if tool_name == "map_risk_drivers":
        risk_card = map_risk_drivers(bundle)
        risk_cache_key = f"risk:{sharp.fhir_base_url}:{sharp.patient_id}"
        _risk_cache.set(risk_cache_key, risk_card)
        return _rpc_result(risk_card.model_dump_json(), rpc_id)

    if rpc_id is not None:
        return JSONResponse(
            status_code=200,
            content={"jsonrpc": "2.0", "id": rpc_id,
                     "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}},
        )
    raise HTTPException(status_code=404, detail="Unknown tool name")


# ── SSE streaming endpoint ────────────────────────────────────────────────────

@app.get("/mcp/stream/{tool_name}")
async def stream_tool(tool_name: str, request: Request) -> StreamingResponse:
    """SSE progress stream for long-running SENTINEL tools."""
    sharp = parse_sharp_context(request)
    if not sharp.patient_id:
        raise HTTPException(status_code=400, detail="Missing SHARP patient_id")

    validate_smart_scopes(sharp.access_token)
    user_id = await get_user_identity(request)
    enforce_rate_limit(request, sharp.patient_id)
    audit_log(request, sharp.patient_id, user_id, f"stream:{tool_name}")

    async def _event_stream():
        def _sse(event: str, data: str) -> str:
            return f"event: {event}\ndata: {data}\n\n"

        yield _sse("progress", json.dumps({"step": "fhir_fetch", "status": "started"}))
        bundle = await build_patient_bundle(sharp)
        yield _sse("progress", json.dumps({
            "step": "fhir_fetch", "status": "complete",
            "resources": {
                "conditions": len(bundle.conditions),
                "medications": len(bundle.medications),
                "encounters": len(bundle.encounters),
            },
        }))

        if tool_name == "fhir_discharge_snapshot":
            yield _sse("result", bundle.model_dump_json())

        elif tool_name == "calculate_lace_plus":
            yield _sse("progress", json.dumps({"step": "lace_scoring", "status": "started"}))
            lace = calculate_lace_plus(bundle)
            payload = dict(lace)
            if hasattr(payload.get("risk_level"), "value"):
                payload["risk_level"] = payload["risk_level"].value
            yield _sse("result", json.dumps(payload, default=str))

        elif tool_name == "map_risk_drivers":
            yield _sse("progress", json.dumps({"step": "risk_mapping", "status": "started"}))
            risk_card = map_risk_drivers(bundle)
            yield _sse("progress", json.dumps({
                "step": "risk_mapping", "status": "complete",
                "risk_level": risk_card.risk_level.value,
                "lace_score": risk_card.lace_plus_score,
            }))
            yield _sse("result", risk_card.model_dump_json())

        else:
            yield _sse("error", json.dumps({"detail": f"Unknown tool: {tool_name}"}))

        yield _sse("done", "{}")

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
