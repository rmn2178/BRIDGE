"""AI-generated PCP handoff narratives: structured skeleton + LLM narrative fill."""

from __future__ import annotations

from typing import Optional

import structlog

from bridge_agent.tools.pcp_handoff import draft_pcp_handoff
from sentinel.tools.fhir_snapshot import FHIRBundle
from shared.models import PCPHandoff, RiskCard

_logger = structlog.get_logger("bridge.handoff_ai")

_MIN_WORDS = 300
_MAX_WORDS = 600


def _word_count(text: str) -> int:
    return len(text.split())


async def draft_pcp_handoff_ai(
    risk_card: RiskCard,
    bundle: FHIRBundle,
    llm_client: Optional[object] = None,
) -> PCPHandoff:
    """Draft PCP handoff: deterministic skeleton enriched with AI narrative.

    Falls back to deterministic-only if llm_client is None or LLM fails.
    Validates word count (300-600) before accepting AI output.
    """
    baseline = draft_pcp_handoff(risk_card, bundle)

    if llm_client is None:
        return baseline

    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return baseline

    try:
        enriched = await llm_client.generate_handoff_letter(risk_card, bundle, baseline)
    except Exception as exc:
        _logger.warning("handoff_ai_fallback", error=str(exc), patient_id=risk_card.patient_id)
        return baseline

    # Validate word count — fall back to baseline if out of bounds
    wc = _word_count(enriched.handoff_letter)
    if wc < _MIN_WORDS or wc > _MAX_WORDS:
        _logger.warning(
            "handoff_word_count_out_of_bounds",
            word_count=wc,
            patient_id=risk_card.patient_id,
            fallback="baseline",
        )
        return baseline

    _logger.info(
        "handoff_ai_complete",
        patient_id=risk_card.patient_id,
        word_count=wc,
        ai_enriched=True,
    )
    return enriched
