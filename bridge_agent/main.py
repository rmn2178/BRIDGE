"""FastAPI MCP server for the BRIDGE discharge coordinator."""

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

from bridge_agent.a2a_client import request_risk_assessment
from bridge_agent.tools import care_plan, gap_audit, pcp_handoff
from bridge_agent.tools.care_plan_ai import generate_care_plan_ai
from bridge_agent.tools.handoff_ai import draft_pcp_handoff_ai
from bridge_agent.tools.gap_ai import audit_documentation_gaps_ai
from bridge_agent.tools.debate_ai import run_clinical_debate
from explainability.confidence_scorer import score_confidence
from explainability.reason_trace import build_trace
from common.logging import configure_logging, correlation_middleware
from sentinel.tools.fhir_snapshot import configure_fhir_client, build_patient_bundle
from shared.cache import TTLCache, RedisCache, create_redis_client
from shared.security import audit_log, enforce_rate_limit, get_user_identity, validate_smart_scopes
from shared.sharp import parse_sharp_context

_tool_cache = TTLCache(ttl_seconds=int(os.getenv("TOOLS_CACHE_TTL_SECONDS", "300")))
_logger = structlog.get_logger("bridge")

_TOOLS = [
    {
        "name": "generate_care_plan",
        "description": "Generate prioritised discharge care plan actions from SENTINEL risk assessment.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "draft_pcp_handoff",
        "description": "Draft a structured primary care handoff letter with FHIR-cited medications.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "audit_documentation_gaps",
        "description": "Audit discharge documentation gaps for CMS compliance.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "debate_discharge",
        "description": (
            "Run multi-agent clinical debate on discharge decision. Three specialist agents "
            "(medication_safety, sdoh, continuity) review the patient in parallel and vote "
            "on discharge readiness with full explainability."
        ),
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
    llm_client = None
    if os.getenv("USE_GENAI", "true").lower() == "true":
        try:
            from shared.llm import LLMClient
            llm_client = LLMClient()
            _logger.info("llm_client_initialized", provider=os.getenv("LLM_PROVIDER", "openai"))
        except Exception as exc:
            _logger.warning("llm_client_init_failed", error=str(exc))
    app.state.llm_client = llm_client
    yield
    await client.aclose()
    if redis_client:
        await redis_client.aclose()


app = FastAPI(title="BRIDGE MCP", version="1.0.0", lifespan=lifespan)

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
    return {"status": "ok", "service": "bridge"}


@app.get("/agent-card")
async def agent_card() -> dict:
    """Prompt Opinion marketplace discovery endpoint."""
    base = os.getenv("BRIDGE_URL", "http://localhost:8002")
    sentinel_url = os.getenv("SENTINEL_URL", "http://localhost:8001")
    return {
        "name": "bridge-discharge-coordinator",
        "display_name": "BRIDGE Discharge Coordinator",
        "description": (
            "Multi-agent discharge coordination system. Orchestrates SENTINEL risk intelligence "
            "via A2A to generate care plans, PCP handoff letters, and CMS documentation gap "
            "audits — all with SHARP context propagation and FHIR citations."
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
            "fhir_r4", "a2a_orchestration", "care_plan_generation",
            "cms_gap_audit", "pcp_handoff", "sse_streaming", "audit_trail",
            "genai_care_plans", "genai_handoffs", "ai_gap_prioritization",
            "multi_agent_debate", "clinical_explainability", "confidence_scoring",
        ],
        "fhir_resources": [
            "Patient", "Condition", "MedicationRequest", "Observation",
            "Encounter", "AllergyIntolerance", "Appointment",
        ],
        "tools": _TOOLS,
        "a2a_dependencies": [
            {"name": "sentinel-risk-stratifier", "url": f"{sentinel_url}/agent-card"},
        ],
        "data_usage": "synthetic_only",
        "compliance": ["HIPAA_audit_log", "SSRF_protected", "rate_limited", "CMS_gap_audit", "no_real_PHI"],
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

    try:
        risk_card = await request_risk_assessment(sharp)
    except HTTPException as exc:
        raise HTTPException(status_code=503, detail=f"A2A handshake with SENTINEL failed: {exc.detail}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"A2A handshake with SENTINEL failed: {exc}")

    llm = getattr(request.app.state, "llm_client", None)

    if tool_name == "generate_care_plan":
        bundle = await build_patient_bundle(sharp)
        plan = await generate_care_plan_ai(risk_card, llm)
        debate = await run_clinical_debate(risk_card, bundle, llm)
        approve_ratio = debate.approve_count / debate.vote_count if debate.vote_count else 1.0
        confidence = score_confidence(risk_card, approve_ratio)
        trace = build_trace(
            patient_id=sharp.patient_id,
            tool_called="generate_care_plan",
            risk_card=risk_card,
            reasoning_path=["sentinel_a2a", "care_plan_ai", "debate", "synthesis"],
            fallback_used=(llm is None),
            debate_result=debate,
            confidence=confidence,
        )
        result = {
            "care_plan": json.loads(plan.model_dump_json()),
            "debate": json.loads(debate.model_dump_json()),
            "confidence": json.loads(confidence.model_dump_json()),
            "reason_trace": json.loads(trace.model_dump_json()),
        }
        return _rpc_result(json.dumps(result), rpc_id)

    if tool_name == "draft_pcp_handoff":
        bundle = await build_patient_bundle(sharp)
        handoff = await draft_pcp_handoff_ai(risk_card, bundle, llm)
        return _rpc_result(handoff.model_dump_json(), rpc_id)

    if tool_name == "audit_documentation_gaps":
        bundle = await build_patient_bundle(sharp)
        audit = await audit_documentation_gaps_ai(risk_card, bundle, llm)
        return _rpc_result(audit.model_dump_json(), rpc_id)

    if tool_name == "debate_discharge":
        bundle = await build_patient_bundle(sharp)
        debate = await run_clinical_debate(risk_card, bundle, llm)
        approve_ratio = debate.approve_count / debate.vote_count if debate.vote_count else 1.0
        confidence = score_confidence(risk_card, approve_ratio)
        trace = build_trace(
            patient_id=sharp.patient_id,
            tool_called="debate_discharge",
            risk_card=risk_card,
            reasoning_path=["sentinel_a2a", "debate_pharmacy", "debate_sdoh", "debate_continuity", "synthesis"],
            fallback_used=(llm is None),
            debate_result=debate,
            confidence=confidence,
        )
        result = {
            "debate": json.loads(debate.model_dump_json()),
            "confidence": json.loads(confidence.model_dump_json()),
            "reason_trace": json.loads(trace.model_dump_json()),
        }
        return _rpc_result(json.dumps(result), rpc_id)

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
    """SSE progress stream for long-running BRIDGE tools."""
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

        yield _sse("progress", json.dumps({"step": "sentinel_a2a", "status": "started"}))
        try:
            risk_card = await request_risk_assessment(sharp)
        except Exception as exc:
            yield _sse("error", json.dumps({"detail": str(exc)}))
            return
        yield _sse("progress", json.dumps({
            "step": "sentinel_a2a", "status": "complete",
            "risk_level": risk_card.risk_level.value,
            "lace_score": risk_card.lace_plus_score,
        }))

        if tool_name in ("draft_pcp_handoff", "audit_documentation_gaps", "debate_discharge"):
            yield _sse("progress", json.dumps({"step": "fhir_fetch", "status": "started"}))
            bundle = await build_patient_bundle(sharp)
            yield _sse("progress", json.dumps({"step": "fhir_fetch", "status": "complete"}))
        else:
            bundle = None

        yield _sse("progress", json.dumps({"step": tool_name, "status": "started"}))

        llm = getattr(request.app.state, "llm_client", None)
        if tool_name == "generate_care_plan":
            result = await generate_care_plan_ai(risk_card, llm)
            yield _sse("result", result.model_dump_json())
        elif tool_name == "draft_pcp_handoff" and bundle:
            result = await draft_pcp_handoff_ai(risk_card, bundle, llm)
            yield _sse("result", result.model_dump_json())
        elif tool_name == "audit_documentation_gaps" and bundle:
            result = await audit_documentation_gaps_ai(risk_card, bundle, llm)
            yield _sse("result", result.model_dump_json())
        elif tool_name == "debate_discharge" and bundle:
            from agents import medication_safety_agent, sdoh_agent, continuity_agent

            yield _sse("progress", json.dumps({"step": "agent_dispatch", "status": "started",
                                                "agents": ["medication_safety", "sdoh", "continuity"]}))

            # Run agents in parallel, emit each vote as it arrives
            agent_modules = [
                ("medication_safety", medication_safety_agent),
                ("sdoh", sdoh_agent),
                ("continuity", continuity_agent),
            ]
            tasks = {
                name: asyncio.create_task(mod.review_discharge(risk_card, bundle, llm))
                for name, mod in agent_modules
            }
            votes = []
            for name, task in tasks.items():
                vote = await task
                votes.append(vote)
                emoji = "✅" if vote.approval else "⚠️"
                yield _sse("agent_vote", json.dumps({
                    "agent": vote.agent_name,
                    "approval": vote.approval,
                    "confidence": vote.confidence,
                    "primary_concern": vote.primary_concern,
                    "blocking_factors": vote.blocking_factors,
                    "display": f"{emoji} {vote.agent_name}: {vote.primary_concern}",
                }))

            yield _sse("progress", json.dumps({"step": "consensus_calculation", "status": "started"}))

            from bridge_agent.tools.debate_ai import _deterministic_consensus, _llm_arbitrate
            baseline = _deterministic_consensus(votes, risk_card.patient_id)
            is_split = 0 < baseline.block_count < baseline.vote_count
            if is_split and llm is not None:
                debate_result = await _llm_arbitrate(votes, risk_card, llm, baseline)
            else:
                debate_result = baseline

            yield _sse("consensus", json.dumps({
                "consensus": debate_result.consensus,
                "confidence": debate_result.confidence,
                "approve_count": debate_result.approve_count,
                "block_count": debate_result.block_count,
                "vote_count": debate_result.vote_count,
                "arbitration": debate_result.arbitration,
            }))

            approve_ratio = debate_result.approve_count / debate_result.vote_count if debate_result.vote_count else 1.0
            confidence = score_confidence(risk_card, approve_ratio)
            yield _sse("confidence", json.dumps({
                "score": confidence.score,
                "level": confidence.level,
                "factors": [f.model_dump() for f in confidence.key_factors],
            }))

            yield _sse("result", debate_result.model_dump_json())
        else:
            yield _sse("error", json.dumps({"detail": f"Unknown tool: {tool_name}"}))
            return

        yield _sse("done", "{}")

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
