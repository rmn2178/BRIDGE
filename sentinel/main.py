"""FastAPI MCP server for the SENTINEL risk stratifier."""

from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from shared.sharp import parse_sharp_context
from sentinel.tools.fhir_snapshot import build_patient_bundle
from sentinel.tools.lace_plus import calculate_lace_plus
from sentinel.tools.risk_mapper import map_risk_drivers

app = FastAPI(title="SENTINEL MCP")


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
async def list_tools() -> dict:
    """Expose MCP tool definitions."""

    return {"tools": tools}


@app.post("/mcp/call")
async def call_tool(request: Request, call: MCPCall) -> dict:
    """Dispatch MCP tool requests to SENTINEL tooling."""

    sharp = parse_sharp_context(request)
    if not sharp.patient_id:
        raise HTTPException(status_code=400, detail="Missing SHARP patient_id")

    bundle = await build_patient_bundle(sharp)

    if call.name == "fhir_discharge_snapshot":
        return _mcp_envelope(bundle.model_dump_json())
    if call.name == "calculate_lace_plus":
        lace = calculate_lace_plus(bundle)
        return _mcp_envelope(json.dumps(lace, default=str))
    if call.name == "map_risk_drivers":
        risk_card = map_risk_drivers(bundle)
        return _mcp_envelope(risk_card.model_dump_json())

    raise HTTPException(status_code=404, detail="Unknown tool name")
