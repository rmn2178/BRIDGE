"""Utilities for parsing SHARP context headers from FastAPI requests."""

from fastapi import HTTPException, Request

from common.errors import ValidationError as BridgeValidationError

from shared.models import SHARPContext


def parse_sharp_context(request: Request) -> SHARPContext:
    """Parse SHARP headers from an incoming request into SHARPContext."""

    patient_id = request.headers.get("x-sharp-patient-id", "").strip()
    fhir_base_url = request.headers.get(
        "x-sharp-fhir-base-url", "https://hapi.fhir.org/baseR4"
    ).strip()
    access_token = request.headers.get("x-sharp-access-token", "").strip()
    encounter_id = request.headers.get("x-sharp-encounter-id")
    practitioner_id = request.headers.get("x-sharp-practitioner-id")

    try:
        return SHARPContext(
            patient_id=patient_id,
            fhir_base_url=fhir_base_url,
            access_token=access_token,
            encounter_id=encounter_id,
            practitioner_id=practitioner_id,
        )
    except (ValueError, BridgeValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
