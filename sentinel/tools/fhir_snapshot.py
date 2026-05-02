"""FHIR snapshot builder for constructing a discharge data bundle."""

from __future__ import annotations

from typing import List

import httpx
from pydantic import BaseModel

from shared.models import SHARPContext


class FHIRBundle(BaseModel):
    """Normalized collection of FHIR resources for a patient."""

    patient: dict
    conditions: List[dict]
    medications: List[dict]
    observations: List[dict]
    encounters: List[dict]
    allergies: List[dict]
    appointments: List[dict]


async def _fetch_json(client: httpx.AsyncClient, url: str, headers: dict) -> dict | None:
    try:
        response = await client.get(url, headers=headers)
    except Exception:
        return None

    if response.status_code != 200:
        return None
    try:
        return response.json()
    except Exception:
        return None


def _extract_bundle_resources(payload: dict | None) -> List[dict]:
    if not isinstance(payload, dict):
        return []
    entries = payload.get("entry", [])
    resources: List[dict] = []
    for entry in entries:
        if isinstance(entry, dict):
            resource = entry.get("resource")
            if isinstance(resource, dict):
                resources.append(resource)
    return resources


async def build_patient_bundle(sharp: SHARPContext) -> FHIRBundle:
    """Fetch patient-centered FHIR resources with resilient error handling."""

    base_url = sharp.fhir_base_url.rstrip("/")
    headers: dict[str, str] = {}
    if sharp.access_token:
        headers["Authorization"] = f"Bearer {sharp.access_token}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        patient_payload = await _fetch_json(
            client, f"{base_url}/Patient/{sharp.patient_id}", headers
        )
        conditions_payload = await _fetch_json(
            client, f"{base_url}/Condition?patient={sharp.patient_id}", headers
        )
        medications_payload = await _fetch_json(
            client, f"{base_url}/MedicationRequest?patient={sharp.patient_id}", headers
        )
        observations_payload = await _fetch_json(
            client, f"{base_url}/Observation?patient={sharp.patient_id}", headers
        )
        encounters_payload = await _fetch_json(
            client, f"{base_url}/Encounter?patient={sharp.patient_id}", headers
        )
        allergies_payload = await _fetch_json(
            client, f"{base_url}/AllergyIntolerance?patient={sharp.patient_id}", headers
        )
        appointments_payload = await _fetch_json(
            client, f"{base_url}/Appointment?patient={sharp.patient_id}", headers
        )

    patient_resource = patient_payload if isinstance(patient_payload, dict) else {}

    return FHIRBundle(
        patient=patient_resource,
        conditions=_extract_bundle_resources(conditions_payload),
        medications=_extract_bundle_resources(medications_payload),
        observations=_extract_bundle_resources(observations_payload),
        encounters=_extract_bundle_resources(encounters_payload),
        allergies=_extract_bundle_resources(allergies_payload),
        appointments=_extract_bundle_resources(appointments_payload),
    )
