"""Multi-agent clinical debate orchestrator."""

from __future__ import annotations

import asyncio
import json
from typing import List, Optional

import structlog

from agents import medication_safety_agent, sdoh_agent, continuity_agent
from shared.models import AgentVote, ConsensusPlan, DebateResult, RiskCard
from sentinel.tools.fhir_snapshot import FHIRBundle

_logger = structlog.get_logger("bridge.debate")

_ARBITRATOR_SYSTEM = (
    "You are a senior physician arbitrating a clinical discharge debate. "
    "You have received votes from specialist agents. Synthesise their concerns into a "
    "consensus decision and a concrete action plan. "
    "Output strict JSON matching DebateResult schema fields: "
    "consensus (APPROVE|APPROVE_WITH_CONDITIONS|OBJECT_WITH_CONCERNS|BLOCK), "
    "confidence (0-1), arbitration (string explanation), "
    "synthesis_plan (mandatory_conditions[], recommended_actions[], "
    "monitoring_requirements[], discharge_timeline). "
    "SAFETY RAILS: Never invent clinical data. Address every blocking factor."
)


def _deterministic_consensus(votes: List[AgentVote], patient_id: str) -> DebateResult:
    """Rule-based consensus — no LLM required."""
    approve_count = sum(1 for v in votes if v.approval)
    block_count = len(votes) - approve_count
    dissenting = [v for v in votes if not v.approval]

    all_blocking = list({bf for v in votes for bf in v.blocking_factors})
    all_actions = list({a for v in votes for a in v.suggested_actions})
    avg_confidence = sum(v.confidence for v in votes) / len(votes) if votes else 0.5

    if block_count == 0:
        consensus = "APPROVE"
    elif block_count == len(votes):
        consensus = "BLOCK"
    elif all_blocking:
        consensus = "APPROVE_WITH_CONDITIONS"
    else:
        consensus = "OBJECT_WITH_CONCERNS"

    arbitration = (
        f"{approve_count}/{len(votes)} agents approved. "
        f"{'Blocking factors: ' + '; '.join(all_blocking[:3]) + '.' if all_blocking else 'No blocking factors.'} "
        f"Consensus reached by majority vote with mandatory conditions from dissenting agents."
    )

    return DebateResult(
        patient_id=patient_id,
        consensus=consensus,
        confidence=round(avg_confidence, 2),
        vote_count=len(votes),
        approve_count=approve_count,
        block_count=block_count,
        agent_votes=votes,
        dissenting_votes=dissenting,
        synthesis_plan=ConsensusPlan(
            mandatory_conditions=all_blocking,
            recommended_actions=all_actions[:5],
            monitoring_requirements=[
                a for a in all_actions if any(
                    kw in a.lower() for kw in ("monitor", "check", "review", "weight", "inr")
                )
            ][:3],
            discharge_timeline="Within 24-48 hours pending resolution of mandatory conditions"
            if all_blocking else "Standard discharge timeline",
        ),
        arbitration=arbitration,
    )


async def _llm_arbitrate(
    votes: List[AgentVote],
    risk_card: RiskCard,
    llm_client: object,
    baseline: DebateResult,
) -> DebateResult:
    """LLM arbitration for split decisions."""
    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return baseline

    user = json.dumps({
        "patient_id": risk_card.patient_id,
        "lace_plus_score": risk_card.lace_plus_score,
        "risk_level": risk_card.risk_level.value,
        "agent_votes": [v.model_dump() for v in votes],
        "approve_count": baseline.approve_count,
        "block_count": baseline.block_count,
        "instruction": (
            "Arbitrate this clinical debate. Return JSON with: "
            "consensus, confidence, arbitration, synthesis_plan "
            "(mandatory_conditions[], recommended_actions[], "
            "monitoring_requirements[], discharge_timeline)."
        ),
    })

    try:
        raw = await llm_client._chat(_ARBITRATOR_SYSTEM, user, llm_client._model, 0.2)
        data = json.loads(raw)
        plan_data = data.get("synthesis_plan", {})
        return DebateResult(
            patient_id=risk_card.patient_id,
            consensus=data.get("consensus", baseline.consensus),
            confidence=float(data.get("confidence", baseline.confidence)),
            vote_count=baseline.vote_count,
            approve_count=baseline.approve_count,
            block_count=baseline.block_count,
            agent_votes=votes,
            dissenting_votes=baseline.dissenting_votes,
            synthesis_plan=ConsensusPlan(
                mandatory_conditions=plan_data.get("mandatory_conditions", baseline.synthesis_plan.mandatory_conditions),
                recommended_actions=plan_data.get("recommended_actions", baseline.synthesis_plan.recommended_actions),
                monitoring_requirements=plan_data.get("monitoring_requirements", baseline.synthesis_plan.monitoring_requirements),
                discharge_timeline=plan_data.get("discharge_timeline", baseline.synthesis_plan.discharge_timeline),
            ),
            arbitration=data.get("arbitration", baseline.arbitration),
        )
    except Exception as exc:
        _logger.warning("arbitration_llm_fallback", error=str(exc))
        return baseline


async def run_clinical_debate(
    risk_card: RiskCard,
    bundle: FHIRBundle,
    llm_client: Optional[object] = None,
) -> DebateResult:
    """Run parallel specialist agent debate and synthesise consensus.

    Falls back to deterministic consensus if LLM unavailable.
    Always returns a valid DebateResult regardless of failures.
    """
    _logger.info("debate_started", patient_id=risk_card.patient_id)

    # Run all three agents in parallel
    try:
        votes: List[AgentVote] = list(await asyncio.gather(
            medication_safety_agent.review_discharge(risk_card, bundle, llm_client),
            sdoh_agent.review_discharge(risk_card, bundle, llm_client),
            continuity_agent.review_discharge(risk_card, bundle, llm_client),
        ))
    except Exception as exc:
        _logger.warning("debate_agents_failed", error=str(exc))
        votes = [
            await medication_safety_agent.review_discharge(risk_card, bundle, None),
            await sdoh_agent.review_discharge(risk_card, bundle, None),
            await continuity_agent.review_discharge(risk_card, bundle, None),
        ]

    baseline = _deterministic_consensus(votes, risk_card.patient_id)

    # Only call LLM arbitrator on split decisions
    is_split = 0 < baseline.block_count < baseline.vote_count
    if is_split and llm_client is not None:
        result = await _llm_arbitrate(votes, risk_card, llm_client, baseline)
    else:
        result = baseline

    _logger.info(
        "debate_complete",
        patient_id=risk_card.patient_id,
        consensus=result.consensus,
        confidence=result.confidence,
        approve=result.approve_count,
        block=result.block_count,
    )
    return result
