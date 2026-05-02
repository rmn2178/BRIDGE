"""Simple latency benchmark for BRIDGE endpoints."""

from __future__ import annotations

import json
import time
from statistics import mean, quantiles

import httpx

FHIR_BASE = "https://hapi.fhir.org/baseR4"
PATIENT_ID = "bridge-demo-001"


def run_benchmark(url: str, payload: dict, iterations: int = 20) -> dict:
    headers = {
        "Content-Type": "application/json",
        "x-sharp-patient-id": PATIENT_ID,
        "x-sharp-fhir-base-url": FHIR_BASE,
        "x-sharp-access-token": "",
    }
    timings = []
    with httpx.Client(timeout=10.0) as client:
        for _ in range(iterations):
            start = time.perf_counter()
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            timings.append((time.perf_counter() - start) * 1000.0)
    p50, p95, p99 = quantiles(timings, n=100)[49], quantiles(timings, n=100)[94], quantiles(timings, n=100)[98]
    return {
        "count": len(timings),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "mean_ms": round(mean(timings), 2),
    }


if __name__ == "__main__":
    results = {
        "sentinel_map_risk": run_benchmark(
            "http://localhost:8001/mcp/call", {"name": "map_risk_drivers", "arguments": {}}
        ),
        "bridge_care_plan": run_benchmark(
            "http://localhost:8002/mcp/call", {"name": "generate_care_plan", "arguments": {}}
        ),
        "bridge_gap_audit": run_benchmark(
            "http://localhost:8002/mcp/call", {"name": "audit_documentation_gaps", "arguments": {}}
        ),
    }
    print(json.dumps(results, indent=2))
