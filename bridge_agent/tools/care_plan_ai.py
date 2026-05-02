"""AI-enhanced care plan generation: deterministic baseline + LLM enrichment."""

from __future__ import annotations

from typing import Optional

import structlog

from bridge_agent.tools.care_plan import generate_care_plan
from shared.models import CarePlanOutput, RiskCard

_logger = structlog.get_logger("bridge.care_plan_ai")


async def generate_care_plan_ai(
    risk_card: RiskCard,
    llm_client: Optional[object] = None,
) -> CarePlanOutput:
    """Generate care plan: deterministic baseline merged with LLM enrichment.

    Falls back to deterministic-only if llm_client is None or LLM fails.
    CRITICAL baseline actions are always preserved regardless of LLM output.
    """
    baseline = generate_care_plan(risk_card)

    if llm_client is None:
        return baseline

    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return baseline

    try:
        enriched = await llm_client.generate_care_plan(risk_card, baseline)
    except Exception as exc:
        _logger.warning("care_plan_ai_fallback", error=str(exc), patient_id=risk_card.patient_id)
        return baseline

    # Merge: baseline actions ∪ LLM additions, dedup by action text
    existing_actions = {a.action.lower() for a in enriched.actions}
    for action in baseline.actions:
        if action.action.lower() not in existing_actions:
            enriched.actions.append(action)
            existing_actions.add(action.action.lower())

    # Generate adaptive patient instructions if LLM available
    instructions = await llm_client.generate_patient_instructions(risk_card, reading_level="8th")
    if instructions:
        enriched = CarePlanOutput(
            patient_id=enriched.patient_id,
            actions=enriched.actions,
            patient_instructions=instructions,
            clinician_summary=enriched.clinician_summary,
        )

    _logger.info(
        "care_plan_ai_complete",
        patient_id=risk_card.patient_id,
        baseline_actions=len(baseline.actions),
        final_actions=len(enriched.actions),
        ai_enriched=True,
    )
    return enriched
