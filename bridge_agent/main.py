"""FastAPI MCP server for the BRIDGE discharge coordinator."""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from bridge_agent.a2a_client import request_risk_assessment
from bridge_agent.tools import care_plan, gap_audit, pcp_handoff
from shared.sharp import parse_sharp_context
from sentinel.tools.fhir_snapshot import build_patient_bundle

app = FastAPI(title="BRIDGE MCP")


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
async def list_tools() -> dict:
    """Expose MCP tool definitions."""

    return {"tools": tools}


@app.post("/mcp/call")
async def call_tool(request: Request, call: MCPCall) -> dict:
    """Dispatch MCP tool requests to BRIDGE tooling."""

    sharp = parse_sharp_context(request)
    if not sharp.patient_id:
        raise HTTPException(status_code=400, detail="Missing SHARP patient_id")

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

    bundle = await build_patient_bundle(sharp)

    if call.name == "draft_pcp_handoff":
        handoff = pcp_handoff.draft_pcp_handoff(risk_card, bundle)
        return _mcp_envelope(handoff.model_dump_json())

    if call.name == "audit_documentation_gaps":
        audit = gap_audit.audit_documentation_gaps(risk_card, bundle)
        return _mcp_envelope(audit.model_dump_json())

    raise HTTPException(status_code=404, detail="Unknown tool name")
