# BRIDGE

Two-agent discharge coordination system using MCP, A2A, SHARP headers, and FHIR R4.

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

- SENTINEL_URL: override Sentinel endpoint for A2A discovery.
- MARKETPLACE_URL: registry for agent discovery.
- PORT: port for container startup.

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
   - `MARKETPLACE_URL=https://app.promptopinion.ai/api/agents`
4. Configure health checks to `/mcp/tools`.

## 10-Day Execution Checklist

| Day | Deliverable | Owner | Status |
| --- | --- | --- | --- |
| 1 | Confirm requirements, stakeholders, and success metrics | Product | Pending |
| 2 | Stand up FHIR sandbox data and access | Data | Pending |
| 3 | Implement SENTINEL MCP tools | Engineering | Pending |
| 4 | Implement BRIDGE MCP tools | Engineering | Pending |
| 5 | Validate LACE+ scoring against golden patient | Clinical | Pending |
| 6 | Draft care plan and handoff templates | Clinical | Pending |
| 7 | Run end-to-end A2A integration tests | Engineering | Pending |
| 8 | Review CMS gap audit outputs with compliance | Compliance | Pending |
| 9 | Deploy staging on Render/Railway/Fly.io | DevOps | Pending |
| 10 | Execute go-live checklist and monitoring | Operations | Pending |
