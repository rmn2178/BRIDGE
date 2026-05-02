"""FHIR snapshot builder for constructing a discharge data bundle."""

from __future__ import annotations

from typing import List, Optional
import os
import asyncio

import httpx
from pydantic import BaseModel

from shared.models import SHARPContext
from shared.cache import RedisCache, RequestCoalescer, TTLCache


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


_http_client: Optional[httpx.AsyncClient] = None
_redis_cache: Optional[RedisCache] = None
_coalescer = RequestCoalescer()
_bundle_cache = TTLCache(ttl_seconds=int(os.getenv("BUNDLE_L1_TTL_SECONDS", "300")))


def configure_fhir_client(client: httpx.AsyncClient, redis_cache: Optional[RedisCache]) -> None:
    global _http_client, _redis_cache
    _http_client = client
    _redis_cache = redis_cache


async def build_patient_bundle(sharp: SHARPContext) -> FHIRBundle:
    """Fetch patient-centered FHIR resources with resilient error handling."""
    base_url = sharp.fhir_base_url.rstrip("/")
    cache_key = f"bundle:{base_url}:{sharp.patient_id}"
    cached = _bundle_cache.get(cache_key)
    if cached:
        return FHIRBundle(**cached)

    if _redis_cache and _redis_cache.enabled:
        cached_redis = await _redis_cache.get_json(cache_key)
        if cached_redis:
            _bundle_cache.set(cache_key, cached_redis)
            return FHIRBundle(**cached_redis)
    headers: dict[str, str] = {}
    if sharp.access_token:
        headers["Authorization"] = f"Bearer {sharp.access_token}"

    lock = _coalescer.lock_for(cache_key)
    async with lock:
        cached = _bundle_cache.get(cache_key)
        if cached:
            return FHIRBundle(**cached)

        if _redis_cache and _redis_cache.enabled:
            cached_redis = await _redis_cache.get_json(cache_key)
            if cached_redis:
                _bundle_cache.set(cache_key, cached_redis)
                return FHIRBundle(**cached_redis)

        client = _http_client or httpx.AsyncClient(timeout=20.0)
        close_client = _http_client is None

        try:
            patient_payload, conditions_payload, medications_payload, observations_payload, encounters_payload, allergies_payload, appointments_payload = await asyncio.gather(
                _fetch_json(client, f"{base_url}/Patient/{sharp.patient_id}", headers),
                _fetch_json(client, f"{base_url}/Condition?patient={sharp.patient_id}", headers),
                _fetch_json(client, f"{base_url}/MedicationRequest?patient={sharp.patient_id}", headers),
                _fetch_json(client, f"{base_url}/Observation?patient={sharp.patient_id}", headers),
                _fetch_json(client, f"{base_url}/Encounter?patient={sharp.patient_id}", headers),
                _fetch_json(client, f"{base_url}/AllergyIntolerance?patient={sharp.patient_id}", headers),
                _fetch_json(client, f"{base_url}/Appointment?patient={sharp.patient_id}", headers),
            )
        finally:
            if close_client:
                await client.aclose()

    patient_resource = patient_payload if isinstance(patient_payload, dict) else {}

    bundle = FHIRBundle(
        patient=patient_resource,
        conditions=_extract_bundle_resources(conditions_payload),
        medications=_extract_bundle_resources(medications_payload),
        observations=_extract_bundle_resources(observations_payload),
        encounters=_extract_bundle_resources(encounters_payload),
        allergies=_extract_bundle_resources(allergies_payload),
        appointments=_extract_bundle_resources(appointments_payload),
    )

    serialized = bundle.model_dump()
    _bundle_cache.set(cache_key, serialized)
    if _redis_cache and _redis_cache.enabled:
        await _redis_cache.set_json(
            cache_key,
            serialized,
            ttl_seconds=int(os.getenv("BUNDLE_REDIS_TTL_SECONDS", "600")),
        )

    return bundle
