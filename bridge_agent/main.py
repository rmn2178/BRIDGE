"""FastAPI MCP server for the BRIDGE discharge coordinator."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import httpx
from pydantic import BaseModel, Field
import structlog

from bridge_agent.a2a_client import request_risk_assessment
from starlette.responses import JSONResponse
from bridge_agent.tools import care_plan, gap_audit, pcp_handoff
from shared.sharp import parse_sharp_context
from shared.security import audit_log, enforce_rate_limit, get_user_identity
from shared.cache import TTLCache, RedisCache, create_redis_client
from sentinel.tools.fhir_snapshot import configure_fhir_client
from sentinel.tools.fhir_snapshot import build_patient_bundle
from common.logging import configure_logging, correlation_middleware

_tool_cache = TTLCache(ttl_seconds=int(os.getenv("TOOLS_CACHE_TTL_SECONDS", "300")))
_logger = structlog.get_logger("bridge")


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


app = FastAPI(title="BRIDGE MCP", lifespan=lifespan)

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
        "name": "generate_care_plan",
        "description": "Generate discharge care plan actions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "draft_pcp_handoff",
        "description": "Draft primary care handoff letter.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "audit_documentation_gaps",
        "description": "Audit discharge documentation gaps for CMS compliance.",
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
    """Dispatch MCP tool requests to BRIDGE tooling."""

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

    try:
        risk_card = await request_risk_assessment(sharp)
    except HTTPException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"A2A handshake with SENTINEL failed: {exc.detail}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"A2A handshake with SENTINEL failed: {exc}",
        )

    if call.name == "generate_care_plan":
        plan = care_plan.generate_care_plan(risk_card)
        return _mcp_envelope(plan.model_dump_json())

    if call.name == "draft_pcp_handoff":
        bundle = await build_patient_bundle(sharp)
        handoff = pcp_handoff.draft_pcp_handoff(risk_card, bundle)
        return _mcp_envelope(handoff.model_dump_json())

    if call.name == "audit_documentation_gaps":
        bundle = await build_patient_bundle(sharp)
        audit = gap_audit.audit_documentation_gaps(risk_card, bundle)
        return _mcp_envelope(audit.model_dump_json())

    raise HTTPException(status_code=404, detail="Unknown tool name")
