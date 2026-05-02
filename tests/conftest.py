"""Shared pytest fixtures for BRIDGE verification suite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest
from fastapi.testclient import TestClient

from bridge_agent import main as bridge_main
from shared.models import RiskCard, RiskLevel, SHARPContext
from sentinel import main as sentinel_main
from sentinel.tools.fhir_snapshot import FHIRBundle
from sentinel.tools.risk_mapper import map_risk_drivers


def _load_golden_bundle() -> Dict:
    bundle_path = Path(__file__).resolve().parents[1] / "sentinel" / "data" / "golden_patient.json"
    with bundle_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_resources(raw_bundle: Dict) -> Dict[str, List[dict]]:
    resources: Dict[str, List[dict]] = {}
    for entry in raw_bundle.get("entry", []):
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(resource, dict):
            continue
        resource_type = resource.get("resourceType")
        if not isinstance(resource_type, str):
            continue
        resources.setdefault(resource_type, []).append(resource)
    return resources


@pytest.fixture(scope="session")
def golden_patient_bundle() -> FHIRBundle:
    """Build a FHIRBundle from the golden patient JSON for shared test use."""

    raw_bundle = _load_golden_bundle()
    resources = _extract_resources(raw_bundle)

    return FHIRBundle(
        patient=(resources.get("Patient") or [{}])[0],
        conditions=resources.get("Condition", []),
        medications=resources.get("MedicationRequest", []),
        observations=resources.get("Observation", []),
        encounters=resources.get("Encounter", []),
        allergies=resources.get("AllergyIntolerance", []),
        appointments=resources.get("Appointment", []),
    )


@pytest.fixture(scope="session")
def golden_risk_card(golden_patient_bundle: FHIRBundle) -> RiskCard:
    """Generate a RiskCard for the golden patient bundle."""

    return map_risk_drivers(golden_patient_bundle)


@pytest.fixture(scope="session")
def sharp_context() -> SHARPContext:
    """Provide a canonical SHARPContext for tests."""

    return SHARPContext(
        patient_id="bridge-demo-001",
        fhir_base_url="https://hapi.fhir.org/baseR4",
        access_token="",
        encounter_id="Enc/index-001",
        practitioner_id=None,
    )


@pytest.fixture(scope="function")
def sentinel_client(sharp_context: SHARPContext) -> TestClient:
    """Create a TestClient for the SENTINEL app with SHARP headers."""

    client = TestClient(sentinel_main.app)
    client.headers.update(
        {
            "x-sharp-patient-id": sharp_context.patient_id,
            "x-sharp-fhir-base-url": sharp_context.fhir_base_url,
            "x-sharp-access-token": sharp_context.access_token,
        }
    )
    return client


@pytest.fixture(scope="function")
def bridge_client(
    monkeypatch: pytest.MonkeyPatch, golden_risk_card: RiskCard, sharp_context: SHARPContext
) -> TestClient:
    """Create a TestClient for BRIDGE with A2A call mocked."""

    async def _mock_request_risk_assessment(_: SHARPContext) -> RiskCard:
        return golden_risk_card

    monkeypatch.setattr(bridge_main, "request_risk_assessment", _mock_request_risk_assessment)

    client = TestClient(bridge_main.app)
    client.headers.update(
        {
            "x-sharp-patient-id": sharp_context.patient_id,
            "x-sharp-fhir-base-url": sharp_context.fhir_base_url,
            "x-sharp-access-token": sharp_context.access_token,
        }
    )
    return client


@pytest.fixture(scope="session")
def empty_bundle() -> FHIRBundle:
    """Provide an empty FHIRBundle for edge case tests."""

    return FHIRBundle(
        patient={},
        conditions=[],
        medications=[],
        observations=[],
        encounters=[],
        allergies=[],
        appointments=[],
    )


@pytest.fixture(scope="session")
def minimal_risk_card() -> RiskCard:
    """Provide a minimal RiskCard for low-risk testing scenarios."""

    return RiskCard(
        patient_id="bridge-demo-001",
        lace_plus_score=2,
        risk_level=RiskLevel.LOW,
        primary_drivers=[],
        medication_flags=[],
        sdoh_flags=[],
        pending_labs=[],
        missing_follow_ups=[],
        fhir_citations=[],
    )
