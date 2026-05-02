"""Medication Safety specialist agent."""

from __future__ import annotations

import json
from typing import Optional

import structlog

from shared.models import AgentVote, RiskCard
from sentinel.tools.fhir_snapshot import FHIRBundle

_logger = structlog.get_logger("agent.medication_safety")

_SYSTEM = (
    "You are a clinical pharmacist reviewing a hospital discharge for medication safety. "
    "Focus on: high-risk medications (warfarin, insulin, opioids, digoxin), pending labs that "
    "affect dosing, drug-drug interactions, and monitoring gaps. "
    "Output strict JSON matching AgentVote schema. "
    "SAFETY RAILS: Only cite FHIR IDs present in the input. Never invent drug interactions."
)


async def _deterministic_vote(risk_card: RiskCard, bundle: FHIRBundle) -> AgentVote:
    """Rule-based fallback vote — no LLM required."""
    concerns = []
    blocking = []
    actions = []
    evidence = list(risk_card.fhir_citations[:3])

    has_warfarin = "warfarin" in risk_card.medication_flags
    has_pending_labs = bool(risk_card.pending_labs)
    has_follow_up = bool(bundle.appointments)

    if has_warfarin and not has_follow_up:
        blocking.append("Warfarin active with no INR follow-up scheduled")
        actions.append("Schedule INR check within 72 hours of discharge")
        concerns.append("Anticoagulation monitoring gap")

    if has_pending_labs:
        blocking.append(f"Pending labs unreviewed: {risk_card.pending_labs[0]}")
        actions.append("Review and act on all pending labs before discharge")

    if "furosemide" in risk_card.medication_flags:
        actions.append("Daily weight monitoring; electrolyte check within 7 days")

    approval = len(blocking) == 0
    confidence = 0.90 if not blocking else 0.65

    return AgentVote(
        agent_name="medication_safety",
        approval=approval,
        confidence=confidence,
        primary_concern=concerns[0] if concerns else "No critical medication safety concerns",
        detailed_reasoning=(
            f"Reviewed {len(risk_card.medication_flags)} high-risk medication(s). "
            f"{'Blocking issues found: ' + '; '.join(blocking) if blocking else 'No blocking issues.'}"
        ),
        suggested_actions=actions or ["Continue current medication regimen with standard monitoring"],
        blocking_factors=blocking,
        fhir_evidence=evidence,
    )


async def review_discharge(
    risk_card: RiskCard,
    bundle: FHIRBundle,
    llm_client: Optional[object] = None,
) -> AgentVote:
    """Medication safety review with LLM enrichment and deterministic fallback."""
    baseline = await _deterministic_vote(risk_card, bundle)

    if llm_client is None:
        return baseline

    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return baseline

    med_list = [
        {"id": m.get("id"), "name": m.get("medicationCodeableConcept", {}).get("text", ""),
         "status": m.get("status")}
        for m in bundle.medications
    ]
    user = json.dumps({
        "patient_id": risk_card.patient_id,
        "medication_flags": risk_card.medication_flags,
        "pending_labs": risk_card.pending_labs,
        "fhir_medications": med_list,
        "has_follow_up_appointment": bool(bundle.appointments),
        "fhir_citations": risk_card.fhir_citations,
        "baseline_vote": baseline.model_dump(),
        "instruction": (
            "Review this discharge for medication safety. Return AgentVote JSON with: "
            "agent_name='medication_safety', approval (bool), confidence (0-1), "
            "primary_concern, detailed_reasoning, suggested_actions[], "
            "blocking_factors[], fhir_evidence[]."
        ),
    })

    try:
        raw = await llm_client._chat(_SYSTEM, user, llm_client._model, 0.2)
        vote = AgentVote.model_validate(json.loads(raw))
        vote = vote.model_copy(update={"agent_name": "medication_safety"})
        # Safety: never drop blocking factors the deterministic pass found
        for bf in baseline.blocking_factors:
            if bf not in vote.blocking_factors:
                vote.blocking_factors.append(bf)
        return vote
    except Exception as exc:
        _logger.warning("medication_safety_llm_fallback", error=str(exc))
        return baseline
