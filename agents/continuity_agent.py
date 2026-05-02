"""Care Continuity specialist agent."""

from __future__ import annotations

import json
from typing import Optional

import structlog

from shared.models import AgentVote, RiskCard
from sentinel.tools.fhir_snapshot import FHIRBundle

_logger = structlog.get_logger("agent.continuity")

_SYSTEM = (
    "You are a care transitions nurse reviewing a hospital discharge for care continuity. "
    "Focus on: follow-up appointment scheduling, PCP handoff completeness, medication "
    "reconciliation status, patient education, and readmission risk mitigation. "
    "Output strict JSON matching AgentVote schema. "
    "SAFETY RAILS: Only reference FHIR resources present in the input."
)


async def _deterministic_vote(risk_card: RiskCard, bundle: FHIRBundle) -> AgentVote:
    """Rule-based fallback vote."""
    blocking = []
    actions = []

    has_appointments = bool(bundle.appointments)
    has_medications = bool(bundle.medications)
    has_pending_labs = bool(risk_card.pending_labs)

    if not has_appointments:
        blocking.append("No follow-up appointment scheduled at time of discharge")
        actions.append("Schedule PCP follow-up within 7 days")

    if not has_medications:
        blocking.append("Medication reconciliation not documented")
        actions.append("Complete medication reconciliation before discharge")

    if has_pending_labs:
        actions.append(f"Ensure follow-up plan for: {risk_card.pending_labs[0]}")

    if risk_card.lace_plus_score >= 10:
        actions.append("Enrol in 30-day post-discharge telephonic follow-up programme")

    approval = len(blocking) == 0
    confidence = 0.88 if not blocking else 0.55

    return AgentVote(
        agent_name="continuity",
        approval=approval,
        confidence=confidence,
        primary_concern=(
            blocking[0] if blocking
            else f"Care continuity adequate for LACE+ {risk_card.lace_plus_score} patient"
        ),
        detailed_reasoning=(
            f"Appointments: {'present' if has_appointments else 'MISSING'}. "
            f"Medication reconciliation: {'documented' if has_medications else 'MISSING'}. "
            f"Pending labs: {len(risk_card.pending_labs)}. "
            f"LACE+ score: {risk_card.lace_plus_score}."
        ),
        suggested_actions=actions or ["Proceed with standard discharge checklist"],
        blocking_factors=blocking,
        fhir_evidence=[c for c in risk_card.fhir_citations if "Encounter" in c][:3],
    )


async def review_discharge(
    risk_card: RiskCard,
    bundle: FHIRBundle,
    llm_client: Optional[object] = None,
) -> AgentVote:
    """Care continuity review with LLM enrichment and deterministic fallback."""
    baseline = await _deterministic_vote(risk_card, bundle)

    if llm_client is None:
        return baseline

    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return baseline

    user = json.dumps({
        "patient_id": risk_card.patient_id,
        "lace_plus_score": risk_card.lace_plus_score,
        "risk_level": risk_card.risk_level.value,
        "missing_follow_ups": risk_card.missing_follow_ups,
        "pending_labs": risk_card.pending_labs,
        "has_appointments": bool(bundle.appointments),
        "has_medications": bool(bundle.medications),
        "fhir_citations": risk_card.fhir_citations,
        "baseline_vote": baseline.model_dump(),
        "instruction": (
            "Review this discharge for care continuity and transition safety. "
            "Return AgentVote JSON with agent_name='continuity'."
        ),
    })

    try:
        raw = await llm_client._chat(_SYSTEM, user, llm_client._model, 0.3)
        vote = AgentVote.model_validate(json.loads(raw))
        vote = vote.model_copy(update={"agent_name": "continuity"})
        for bf in baseline.blocking_factors:
            if bf not in vote.blocking_factors:
                vote.blocking_factors.append(bf)
        return vote
    except Exception as exc:
        _logger.warning("continuity_llm_fallback", error=str(exc))
        return baseline
