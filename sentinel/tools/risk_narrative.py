"""Plain-language risk narrative generator for SENTINEL."""

from __future__ import annotations

from typing import Optional

import structlog

from shared.models import RiskCard

_logger = structlog.get_logger("sentinel.risk_narrative")


def _deterministic_narrative(risk_card: RiskCard) -> str:
    """Deterministic fallback narrative — always safe, always available."""
    drivers = ", ".join(d.criterion for d in risk_card.primary_drivers[:2])
    med_text = f" Active high-risk medications: {', '.join(risk_card.medication_flags)}." if risk_card.medication_flags else ""
    sdoh_text = f" Social risk factors: {'; '.join(risk_card.sdoh_flags[:2])}." if risk_card.sdoh_flags else ""
    followup = f" {risk_card.missing_follow_ups[0]}." if risk_card.missing_follow_ups else ""
    return (
        f"This patient is at {risk_card.risk_level.value} readmission risk "
        f"(LACE+ {risk_card.lace_plus_score}/19) primarily due to {drivers}.{med_text}"
        f"{sdoh_text}{followup} "
        "Priority actions should focus on close outpatient follow-up, "
        "medication monitoring, and home support coordination within 48 hours of discharge."
    )


async def generate_risk_narrative(
    risk_card: RiskCard,
    llm_client: Optional[object] = None,
) -> str:
    """Generate plain-language risk narrative, with LLM enrichment when available."""
    if llm_client is None:
        return _deterministic_narrative(risk_card)

    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return _deterministic_narrative(risk_card)

    try:
        narrative = await llm_client.generate_risk_narrative(risk_card)
    except Exception as exc:
        _logger.warning("risk_narrative_fallback", error=str(exc), patient_id=risk_card.patient_id)
        return _deterministic_narrative(risk_card)
    if not narrative or len(narrative.split()) < 30:
        _logger.warning("risk_narrative_too_short", patient_id=risk_card.patient_id)
        return _deterministic_narrative(risk_card)

    _logger.info("risk_narrative_ai_complete", patient_id=risk_card.patient_id,
                 word_count=len(narrative.split()))
    return narrative
