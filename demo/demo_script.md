# BRIDGE Demo Script

1. Load the golden patient into the HAPI sandbox.
2. Start SENTINEL and BRIDGE services locally.
3. Call SENTINEL tools to confirm LACE+ score and RiskCard output.
4. Call BRIDGE tools to generate care plans, PCP handoff, and gap audit.

## Quick Demo Commands

```bash
curl -X POST "https://hapi.fhir.org/baseR4" \
  -H "Content-Type: application/fhir+json" \
  --data-binary @sentinel/data/golden_patient.json
```

```bash
uvicorn sentinel.main:app --host 0.0.0.0 --port 8001
```

```bash
uvicorn bridge_agent.main:app --host 0.0.0.0 --port 8002
```

```bash
curl -X POST "http://localhost:8001/mcp/call" \
  -H "Content-Type: application/json" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:" \
  -d '{"name": "map_risk_drivers", "arguments": {}}'
```

```bash
curl -X POST "http://localhost:8002/mcp/call" \
  -H "Content-Type: application/json" \
  -H "x-sharp-patient-id: bridge-demo-001" \
  -H "x-sharp-fhir-base-url: https://hapi.fhir.org/baseR4" \
  -H "x-sharp-access-token:" \
  -d '{"name": "generate_care_plan", "arguments": {}}'
```
