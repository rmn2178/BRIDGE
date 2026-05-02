"""Security helpers for authentication, validation, audit logging, and rate limiting."""

from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional, Tuple

import jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import structlog

from common.settings import settings
from common.validation import validate_fhir_base_url, validate_optional_id, validate_patient_id

_audit_logger = structlog.get_logger("bridge.audit")


class RateLimiter:
    """Simple in-memory rate limiter for API requests."""

    def __init__(self) -> None:
        self._window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        self._max_requests = int(os.getenv("RATE_LIMIT_PER_WINDOW", "120"))
        self._buckets: Dict[str, Tuple[int, float]] = {}

    def check(self, key: str) -> None:
        if os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "true":
            return
        now = time.time()
        count, window_start = self._buckets.get(key, (0, now))
        if now - window_start >= self._window_seconds:
            count, window_start = 0, now
        count += 1
        self._buckets[key] = (count, window_start)
        if count > self._max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")


rate_limiter = RateLimiter()


async def get_user_identity(request: Request) -> str:
    """Resolve user identity from API key or JWT."""

    api_keys = settings.api_keys
    api_key = request.headers.get("x-api-key")
    if api_key and api_key in api_keys:
        return f"api_key:{api_key[:6]}"

    if not settings.auth_required:
        return "anonymous"

    bearer = HTTPBearer(auto_error=False)
    credentials: Optional[HTTPAuthorizationCredentials] = await bearer(request)
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = credentials.credentials
    if not settings.jwt_secret:
        raise HTTPException(status_code=500, detail="JWT_SECRET not configured")

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "verify_aud": bool(settings.jwt_audience),
                "verify_iss": bool(settings.jwt_issuer),
            },
        )
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    subject = payload.get("sub") or payload.get("client_id") or "unknown"
    return str(subject)


def enforce_rate_limit(request: Request, patient_id: str) -> None:
    host = request.client.host if request.client else "unknown"
    key = request.headers.get("x-api-key") or patient_id or host
    rate_limiter.check(key)


def audit_log(request: Request, patient_id: str, user_id: str, action: str) -> None:
    if os.getenv("AUDIT_LOG_ENABLED", "true").lower() != "true":
        return
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": user_id,
        "patient_id": patient_id,
        "action": action,
        "path": request.url.path,
        "method": request.method,
    }
    correlation_id = getattr(request.state, "correlation_id", None)
    if correlation_id:
        entry["correlation_id"] = correlation_id
    _audit_logger.info("audit", **entry)
