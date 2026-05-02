"""Unit tests for security validation helpers."""

from __future__ import annotations

import os

import pytest
from common.errors import ValidationError as BridgeValidationError

from shared.models import SHARPContext
from common.validation import validate_fhir_base_url, validate_patient_id
from common.settings import refresh_settings


class TestSecurityValidators:
    """Validate SHARPContext input constraints for HIPAA hardening."""

    def test_valid_patient_id_allows_hyphen(self) -> None:
        assert validate_patient_id("bridge-demo-001") == "bridge-demo-001"

    def test_invalid_patient_id_rejected(self) -> None:
        with pytest.raises(BridgeValidationError):
            validate_patient_id("../etc/passwd")

    def test_fhir_base_url_default_allowlist(self) -> None:
        assert validate_fhir_base_url("https://hapi.fhir.org/baseR4")

    def test_fhir_base_url_rejects_http_by_default(self) -> None:
        with pytest.raises(BridgeValidationError):
            validate_fhir_base_url("http://hapi.fhir.org/baseR4")

    def test_sharp_context_rejects_disallowed_host(self, monkeypatch) -> None:
        monkeypatch.setenv("SHARP_FHIR_ALLOWLIST", "example.com")
        refresh_settings()
        try:
            with pytest.raises(BridgeValidationError):
                SHARPContext(
                    patient_id="bridge-demo-001",
                    fhir_base_url="https://hapi.fhir.org/baseR4",
                    access_token="",
                )
        finally:
            monkeypatch.delenv("SHARP_FHIR_ALLOWLIST", raising=False)
            refresh_settings()
