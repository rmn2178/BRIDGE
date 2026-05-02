"""Environment-backed configuration settings."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Centralized settings with environment overrides."""

    sharp_fhir_allowlist: list[str]
    sharp_allow_http: bool
    auth_required: bool
    api_keys: list[str]
    jwt_secret: str
    jwt_algorithm: str
    jwt_issuer: str | None
    jwt_audience: str | None

    @staticmethod
    def _split_env(name: str) -> list[str]:
        raw = os.getenv(name, "").strip()
        if not raw:
            return []
        return [item.strip().lower() for item in raw.split(",") if item.strip()]


settings = Settings(
    sharp_fhir_allowlist=Settings._split_env("SHARP_FHIR_ALLOWLIST"),
    sharp_allow_http=os.getenv("SHARP_ALLOW_HTTP", "false").lower() == "true",
    auth_required=os.getenv("AUTH_REQUIRED", "false").lower() == "true",
    api_keys=Settings._split_env("API_KEYS"),
    jwt_secret=os.getenv("JWT_SECRET", ""),
    jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    jwt_issuer=os.getenv("JWT_ISSUER"),
    jwt_audience=os.getenv("JWT_AUDIENCE"),
)


def refresh_settings() -> None:
    """Reload settings from environment variables."""

    global settings
    settings = Settings(
        sharp_fhir_allowlist=Settings._split_env("SHARP_FHIR_ALLOWLIST"),
        sharp_allow_http=os.getenv("SHARP_ALLOW_HTTP", "false").lower() == "true",
        auth_required=os.getenv("AUTH_REQUIRED", "false").lower() == "true",
        api_keys=Settings._split_env("API_KEYS"),
        jwt_secret=os.getenv("JWT_SECRET", ""),
        jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
        jwt_issuer=os.getenv("JWT_ISSUER"),
        jwt_audience=os.getenv("JWT_AUDIENCE"),
    )
