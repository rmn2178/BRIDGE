"""Validation helpers for request inputs."""

from __future__ import annotations

import ipaddress
from typing import Optional
from urllib.parse import urlparse

import common.settings as _settings_module
from common.constants import DEFAULT_FHIR_BASE_URL, SDOH_PREFIXES
from common.errors import ValidationError


def validate_patient_id(patient_id: str) -> str:
    """Validate patient ID format to reduce injection risk."""

    if patient_id is None:
        raise ValidationError("patient_id is required")
    value = patient_id.strip()
    if not value:
        return value
    if len(value) > 64:
        raise ValidationError("patient_id too long")
    for ch in value:
        if not (ch.isalnum() or ch in {"-", "."}):
            raise ValidationError("patient_id contains invalid characters")
    return value


def validate_optional_id(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) > 64:
        raise ValidationError(f"{field_name} too long")
    return cleaned


def validate_fhir_base_url(url: str) -> str:
    """Validate a FHIR base URL against an allowlist and SSRF protections."""

    if not url:
        raise ValidationError("FHIR base URL is required")
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValidationError("FHIR base URL must be http or https")
    settings = _settings_module.settings
    if parsed.scheme == "http" and not settings.sharp_allow_http:
        raise ValidationError("FHIR base URL must be https")
    if not parsed.hostname:
        raise ValidationError("FHIR base URL missing host")

    hostname = parsed.hostname.lower()
    allowlist = settings.sharp_fhir_allowlist or ["hapi.fhir.org"]
    if hostname not in allowlist:
        raise ValidationError("FHIR base URL not in allowlist")

    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValidationError("FHIR base URL host not allowed")
    except ValueError:
        pass

    return url.rstrip("/")


def normalize_fhir_base_url(url: Optional[str]) -> str:
    if not url:
        return DEFAULT_FHIR_BASE_URL
    return url.strip()
