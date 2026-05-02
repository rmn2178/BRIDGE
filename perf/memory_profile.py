"""Memory usage sampler under steady request load."""

from __future__ import annotations

import os
import time

import httpx
import psutil

FHIR_BASE = os.getenv("FHIR_BASE_URL", "https://hapi.fhir.org/baseR4")
PATIENT_ID = os.getenv("PATIENT_ID", "bridge-demo-001")


def sample_memory(seconds: int = 30) -> None:
    process = psutil.Process()
    headers = {
        "Content-Type": "application/json",
        "x-sharp-patient-id": PATIENT_ID,
        "x-sharp-fhir-base-url": FHIR_BASE,
        "x-sharp-access-token": "",
    }
    payload = {"name": "generate_care_plan", "arguments": {}}
    start = time.time()
    with httpx.Client(timeout=10.0) as client:
        while time.time() - start < seconds:
            client.post("http://localhost:8002/mcp/call", headers=headers, json=payload)
            rss_mb = process.memory_info().rss / (1024 * 1024)
            print(f"{time.time():.0f},{rss_mb:.2f}")
            time.sleep(0.5)


if __name__ == "__main__":
    sample_memory()
