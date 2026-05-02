"""Custom exception types for BRIDGE."""

from __future__ import annotations


class BridgeError(Exception):
    """Base exception for BRIDGE-specific errors."""


class ValidationError(BridgeError):
    """Raised when input validation fails."""


class FHIRFetchError(BridgeError):
    """Raised when a FHIR fetch fails."""
