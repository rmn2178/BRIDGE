"""Unit tests for SHARP header parsing behavior."""

from __future__ import annotations

from starlette.requests import Request

from shared.sharp import parse_sharp_context


def _make_request(headers: dict) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()],
    }
    return Request(scope)


class TestSharpContextParsing:
    """Ensure SHARP headers map cleanly to SHARPContext fields."""

    def test_full_headers_parsed_correctly(self) -> None:
        request = _make_request(
            {
                "x-sharp-patient-id": "bridge-demo-001",
                "x-sharp-fhir-base-url": "https://hapi.fhir.org/baseR4",
                "x-sharp-access-token": "token",
                "x-sharp-encounter-id": "Enc/index-001",
                "x-sharp-practitioner-id": "Practitioner/123",
            }
        )
        ctx = parse_sharp_context(request)
        assert ctx.patient_id == "bridge-demo-001"
        assert ctx.fhir_base_url == "https://hapi.fhir.org/baseR4"
        assert ctx.access_token == "token"
        assert ctx.encounter_id == "Enc/index-001"
        assert ctx.practitioner_id == "Practitioner/123"

    def test_default_fhir_url_when_header_missing(self) -> None:
        request = _make_request({"x-sharp-patient-id": "bridge-demo-001"})
        ctx = parse_sharp_context(request)
        assert ctx.fhir_base_url == "https://hapi.fhir.org/baseR4"

    def test_empty_access_token_when_missing(self) -> None:
        request = _make_request({"x-sharp-patient-id": "bridge-demo-001"})
        ctx = parse_sharp_context(request)
        assert ctx.access_token == ""

    def test_optional_fields_none_when_absent(self) -> None:
        request = _make_request({"x-sharp-patient-id": "bridge-demo-001"})
        ctx = parse_sharp_context(request)
        assert ctx.encounter_id is None
        assert ctx.practitioner_id is None

    def test_patient_id_from_header(self) -> None:
        request = _make_request({"x-sharp-patient-id": "bridge-demo-001"})
        ctx = parse_sharp_context(request)
        assert ctx.patient_id == "bridge-demo-001"
