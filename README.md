# BRIDGE

Two-agent discharge coordination system using MCP, A2A, SHARP headers, and FHIR R4.

> **Safety:** All data is 100% synthetic. No real Protected Health Information (PHI) is used anywhere in this project.

## Architecture

```
             +---------------------------+
             |   EHR / Calling Client    |
             | SHARP headers + MCP call  |
             +-------------+-------------+
                           |
                           v
                 +---------+---------+
                 |       BRIDGE      |
                 |  Care Coordination|
                 |  MCP Server :8002 |
                 +----+---------+----+
                      |         |
                      | A2A     | FHIR
                      v         v
           +----------+--+   +--+------------------+
           |  SENTINEL   |   |  HAPI FHIR Sandbox  |
           | Risk Engine |   | https://hapi.fhir.org|
           | MCP Server  |   +---------------------+
           |     :8001   |
           +-------------+
```

## Setup & Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

## Running SENTINEL Locally

```bash
uvicorn sentinel.main:app --host 0.0.0.0 --port 8001
```

## Running BRIDGE Locally

```bash
uvicorn bridge_agent.main:app --host 0.0.0.0 --port 8002
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SENTINEL_URL` | `http://localhost:8001` | SENTINEL service URL for A2A calls |
| `BRIDGE_URL` | `http://localhost:8002` | BRIDGE public URL (used in agent-card) |
| `MARKETPLACE_URL` | `https://app.promptopinion.ai/api/agents` | Prompt Opinion registry |
| `PORT` | `8001` | Container startup port |
| `REDIS_URL` | _(none)_ | Optional Redis for L2 caching |
| `AUTH_REQUIRED` | `false` | Require JWT bearer token |
| `JWT_SECRET` | _(none)_ | JWT signing secret |
| `API_KEYS` | _(none)_ | Comma-separated API keys |
| `SMART_REQUIRED_SCOPES` | _(none)_ | Comma-separated SMART-on-FHIR scopes to enforce |
| `SHARP_FHIR_ALLOWLIST` | `hapi.fhir.org` | Comma-separated allowed FHIR hosts |
| `AUDIT_LOG_ENABLED` | `true` | Structured audit logging |
| `RATE_LIMIT_PER_WINDOW` | `120` | Max requests per window |

## Marketplace Registration (Prompt Opinion)

Each service exposes a live `/agent-card` endpoint for marketplace discovery:

```bash
# SENTINEL agent card
curl http://localhost:8001/agent-card

# BRIDGE agent card
curl http://localhost:8002/agent-card
```

`GET /` on each service redirects to `/agent-card`.

To register on the Prompt Opinion Marketplace:
1. Deploy both services (see Deployment Guide below)
2. Submit `https://your-sentinel-url.com/agent-card` as the SENTINEL manifest URL
3. Submit `https://your-bridge-url.com/agent-card` as the BRIDGE manifest URL
4. The platform will call `/mcp/tools` to verify tool discovery and `/health` for liveness

## FHIR Setup (HAPI Sandbox)

Load the synthetic patient bundle:

```bash
curl -X POST "https://hapi.fhir.org/baseR4" \
  -H "Content-Type: application/fhir+json" \
  --data-binary @sentinel/data/golden_patient.json
```

## MCP Testing with curl

List tools (SENTINEL):

```bash
curl -X GET "http://localhost:8001/mcp/tools"
```

Call SENTINEL risk mapping:

```bash
curl -X POST "http://localhost:8001/mcp/call" \
  -H "Content-Type: application/json" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:" \
  -d '{"name": "map_risk_drivers", "arguments": {}}'
```

JSON-RPC 2.0 style call:

```bash
curl -X POST "http://localhost:8001/mcp/call" \
  -H "Content-Type: application/json" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "map_risk_drivers"}}'
```

SSE streaming:

```bash
curl -N "http://localhost:8001/mcp/stream/map_risk_drivers" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:"
```

List tools (BRIDGE):

```bash
curl -X GET "http://localhost:8002/mcp/tools"
```

Call BRIDGE care plan:

```bash
curl -X POST "http://localhost:8002/mcp/call" \
  -H "Content-Type: application/json" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:" \
  -d '{"name": "generate_care_plan", "arguments": {}}'
```

Call BRIDGE PCP handoff:

```bash
curl -X POST "http://localhost:8002/mcp/call" \
  -H "Content-Type: application/json" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:" \
  -d '{"name": "draft_pcp_handoff", "arguments": {}}'
```

Call BRIDGE gap audit:

```bash
curl -X POST "http://localhost:8002/mcp/call" \
  -H "Content-Type: application/json" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:" \
  -d '{"name": "audit_documentation_gaps", "arguments": {}}'
```

## Deployment Guide (Render, Railway, Fly.io)

1. Build image: `docker build -t bridge-sentinel .`
2. Deploy two services from the same image:
   - Sentinel service command: `uvicorn sentinel.main:app --host 0.0.0.0 --port ${PORT}`
   - Bridge service command: `uvicorn bridge_agent.main:app --host 0.0.0.0 --port ${PORT}`
3. Set environment variables for BRIDGE:
   - `SENTINEL_URL=https://your-sentinel-url.com`
   - `BRIDGE_URL=https://your-bridge-url.com`
   - `MARKETPLACE_URL=https://app.promptopinion.ai/api/agents`
4. Configure health checks to `/health`.
5. Register agent cards at `/agent-card` on the Prompt Opinion Marketplace.

## Third-Party Licenses

| Dependency | License | Usage |
|---|---|---|
| FastAPI | MIT | HTTP framework |
| Pydantic | MIT | Data validation |
| httpx | BSD-3 | Async HTTP client |
| PyJWT | MIT | JWT validation |
| structlog | MIT/Apache-2 | Structured logging |
| redis | MIT | Optional L2 cache |
| HAPI FHIR (public sandbox) | Apache-2 | Synthetic FHIR data |

All dependencies are open-source and used in compliance with their respective licenses.

## 10-Day Execution Checklist

| Day | Deliverable | Owner | Status |
| --- | --- | --- | --- |
| 1 | Confirm requirements, stakeholders, and success metrics | Product | ✅ Done |
| 2 | Stand up FHIR sandbox data and access | Data | ✅ Done |
| 3 | Implement SENTINEL MCP tools | Engineering | ✅ Done |
| 4 | Implement BRIDGE MCP tools | Engineering | ✅ Done |
| 5 | Validate LACE+ scoring against golden patient | Clinical | ✅ Done |
| 6 | Draft care plan and handoff templates | Clinical | ✅ Done |
| 7 | Run end-to-end A2A integration tests | Engineering | ✅ Done |
| 8 | Review CMS gap audit outputs with compliance | Compliance | ✅ Done |
| 9 | Deploy staging on Render/Railway/Fly.io | DevOps | Pending |
| 10 | Register on Prompt Opinion Marketplace | Operations | Pending |
