"""Reason trace — full decision chain recorder for every MCP tool call."""

from __future__ import annotations

import time
from typing import List, Optional

import structlog

from shared.models import ConfidenceExplanation, DebateResult, ReasonTrace, RiskCard

_logger = structlog.get_logger("bridge.reason_trace")


def build_trace(
    patient_id: str,
    tool_called: str,
    risk_card: RiskCard,
    reasoning_path: List[str],
    fallback_used: bool,
    debate_result: Optional[DebateResult] = None,
    confidence: Optional[ConfidenceExplanation] = None,
) -> ReasonTrace:
    """Build a ReasonTrace for a completed tool call."""
    trace = ReasonTrace(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        patient_id=patient_id,
        tool_called=tool_called,
        lace_plus_score=risk_card.lace_plus_score,
        risk_level=risk_card.risk_level.value,
        reasoning_path=reasoning_path,
        fallback_used=fallback_used,
        debate_result=debate_result,
        confidence=confidence,
    )
    _logger.info(
        "reason_trace",
        patient_id=patient_id,
        tool=tool_called,
        lace=risk_card.lace_plus_score,
        risk_level=risk_card.risk_level.value,
        path=reasoning_path,
        fallback=fallback_used,
        consensus=debate_result.consensus if debate_result else None,
        confidence_score=confidence.score if confidence else None,
    )
    return trace
