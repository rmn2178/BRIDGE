"""Locust performance script for BRIDGE and SENTINEL."""

from __future__ import annotations

import json
import os

from locust import HttpUser, task, between

FHIR_BASE = os.getenv("FHIR_BASE_URL", "https://hapi.fhir.org/baseR4")
PATIENT_ID = os.getenv("PATIENT_ID", "bridge-demo-001")


class SentinelUser(HttpUser):
    wait_time = between(0.01, 0.1)
    host = os.getenv("SENTINEL_HOST", "http://localhost:8001")

    def on_start(self) -> None:
        self.headers = {
            "Content-Type": "application/json",
            "x-sharp-patient-id": PATIENT_ID,
            "x-sharp-fhir-base-url": FHIR_BASE,
            "x-sharp-access-token": "",
        }

    @task(2)
    def map_risk_drivers(self) -> None:
        payload = {"name": "map_risk_drivers", "arguments": {}}
        self.client.post("/mcp/call", headers=self.headers, json=payload)


class BridgeUser(HttpUser):
    wait_time = between(0.01, 0.1)
    host = os.getenv("BRIDGE_HOST", "http://localhost:8002")

    def on_start(self) -> None:
        self.headers = {
            "Content-Type": "application/json",
            "x-sharp-patient-id": PATIENT_ID,
            "x-sharp-fhir-base-url": FHIR_BASE,
            "x-sharp-access-token": "",
        }

    @task(3)
    def generate_care_plan(self) -> None:
        payload = {"name": "generate_care_plan", "arguments": {}}
        self.client.post("/mcp/call", headers=self.headers, json=payload)

    @task(1)
    def audit_documentation_gaps(self) -> None:
        payload = {"name": "audit_documentation_gaps", "arguments": {}}
        self.client.post("/mcp/call", headers=self.headers, json=payload)

    @task(1)
    def draft_pcp_handoff(self) -> None:
        payload = {"name": "draft_pcp_handoff", "arguments": {}}
        self.client.post("/mcp/call", headers=self.headers, json=payload)
