"""SDoH (Social Determinants of Health) specialist agent."""

from __future__ import annotations

import json
from typing import Optional

import structlog

from shared.models import AgentVote, RiskCard
from sentinel.tools.fhir_snapshot import FHIRBundle

_logger = structlog.get_logger("agent.sdoh")

_SYSTEM = (
    "You are a social worker reviewing a hospital discharge for social determinants of health risk. "
    "Focus on: housing instability, living alone, transportation barriers, food insecurity, "
    "missed appointment history, and home support availability. "
    "Output strict JSON matching AgentVote schema. "
    "SAFETY RAILS: Only reference SDoH codes present in the input. Never invent social history."
)

_SDOH_CONCERN_MAP = {
    "Z60.2": "Patient lives alone — limited home support post-discharge",
    "Z59.0": "Housing instability — risk of missed follow-up",
    "Z59.4": "Food insecurity — medication adherence risk",
    "Z63.4": "Caregiver absence — no home monitoring support",
    "Z65.2": "Prior incarceration — potential insurance/access barriers",
}


async def _deterministic_vote(risk_card: RiskCard, bundle: FHIRBundle) -> AgentVote:
    """Rule-based fallback vote."""
    concerns = []
    blocking = []
    actions = []

    for flag in risk_card.sdoh_flags:
        for code, concern in _SDOH_CONCERN_MAP.items():
            if code in flag:
                concerns.append(concern)
                if code in ("Z60.2", "Z59.0"):
                    blocking.append(concern)
                    actions.append("Arrange home health nursing visit within 48 hours")

    if not bundle.appointments and risk_card.missing_follow_ups:
        blocking.append("No follow-up appointment scheduled")
        actions.append("Schedule PCP or cardiology follow-up before discharge")

    approval = len(blocking) == 0
    confidence = 0.85 if not blocking else 0.60

    return AgentVote(
        agent_name="sdoh",
        approval=approval,
        confidence=confidence,
        primary_concern=concerns[0] if concerns else "No critical SDoH barriers identified",
        detailed_reasoning=(
            f"Identified {len(risk_card.sdoh_flags)} SDoH flag(s): "
            f"{', '.join(risk_card.sdoh_flags[:3]) or 'none'}. "
            f"{'Blocking: ' + '; '.join(blocking) if blocking else 'No blocking social barriers.'}"
        ),
        suggested_actions=actions or ["Standard discharge with community resource referral"],
        blocking_factors=blocking,
        fhir_evidence=[c for c in risk_card.fhir_citations if "Observation" in c][:3],
    )


async def review_discharge(
    risk_card: RiskCard,
    bundle: FHIRBundle,
    llm_client: Optional[object] = None,
) -> AgentVote:
    """SDoH review with LLM enrichment and deterministic fallback."""
    baseline = await _deterministic_vote(risk_card, bundle)

    if llm_client is None:
        return baseline

    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return baseline

    user = json.dumps({
        "patient_id": risk_card.patient_id,
        "sdoh_flags": risk_card.sdoh_flags,
        "missing_follow_ups": risk_card.missing_follow_ups,
        "has_appointments": bool(bundle.appointments),
        "lace_plus_score": risk_card.lace_plus_score,
        "fhir_citations": risk_card.fhir_citations,
        "baseline_vote": baseline.model_dump(),
        "instruction": (
            "Review this discharge for social determinants of health risk. "
            "Return AgentVote JSON with agent_name='sdoh'."
        ),
    })

    try:
        raw = await llm_client._chat(_SYSTEM, user, llm_client._model, 0.3)
        vote = AgentVote.model_validate(json.loads(raw))
        vote = vote.model_copy(update={"agent_name": "sdoh"})
        for bf in baseline.blocking_factors:
            if bf not in vote.blocking_factors:
                vote.blocking_factors.append(bf)
        return vote
    except Exception as exc:
        _logger.warning("sdoh_llm_fallback", error=str(exc))
        return baseline
