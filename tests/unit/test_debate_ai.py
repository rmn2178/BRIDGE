"""Unit tests for multi-agent clinical debate engine."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents import medication_safety_agent, sdoh_agent, continuity_agent
from bridge_agent.tools.debate_ai import (
    _deterministic_consensus,
    _llm_arbitrate,
    run_clinical_debate,
)
from explainability.confidence_scorer import score_confidence
from explainability.reason_trace import build_trace
from shared.models import (
    AgentVote,
    ConfidenceExplanation,
    ConsensusPlan,
    DebateResult,
    ReasonTrace,
    RiskCard,
    RiskLevel,
)
from sentinel.tools.fhir_snapshot import FHIRBundle


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_vote(
    agent_name: str,
    approval: bool,
    confidence: float = 0.85,
    blocking: list | None = None,
) -> AgentVote:
    return AgentVote(
        agent_name=agent_name,
        approval=approval,
        confidence=confidence,
        primary_concern="Test concern" if not approval else "No concerns",
        detailed_reasoning="Test reasoning for " + agent_name,
        suggested_actions=["Action 1", "Action 2"],
        blocking_factors=blocking or [],
        fhir_evidence=["Encounter/index-001"],
    )


# ── TestDeterministicConsensus ────────────────────────────────────────────────


class TestDeterministicConsensus:
    def test_unanimous_approve(self) -> None:
        votes = [
            _make_vote("medication_safety", True),
            _make_vote("sdoh", True),
            _make_vote("continuity", True),
        ]
        result = _deterministic_consensus(votes, "bridge-demo-001")
        assert result.consensus == "APPROVE"
        assert result.approve_count == 3
        assert result.block_count == 0
        assert len(result.dissenting_votes) == 0

    def test_unanimous_block(self) -> None:
        votes = [
            _make_vote("medication_safety", False, blocking=["Warfarin gap"]),
            _make_vote("sdoh", False, blocking=["Housing unstable"]),
            _make_vote("continuity", False, blocking=["No follow-up"]),
        ]
        result = _deterministic_consensus(votes, "bridge-demo-001")
        assert result.consensus == "BLOCK"
        assert result.block_count == 3
        assert len(result.dissenting_votes) == 3

    def test_split_with_blocking_factors(self) -> None:
        votes = [
            _make_vote("medication_safety", False, blocking=["Pending BMP"]),
            _make_vote("sdoh", False, blocking=["Lives alone"]),
            _make_vote("continuity", True),
        ]
        result = _deterministic_consensus(votes, "bridge-demo-001")
        assert result.consensus == "APPROVE_WITH_CONDITIONS"
        assert result.approve_count == 1
        assert result.block_count == 2
        assert len(result.synthesis_plan.mandatory_conditions) >= 1

    def test_split_without_blocking_factors(self) -> None:
        votes = [
            _make_vote("medication_safety", False, blocking=[]),
            _make_vote("sdoh", True),
            _make_vote("continuity", True),
        ]
        result = _deterministic_consensus(votes, "bridge-demo-001")
        assert result.consensus == "OBJECT_WITH_CONCERNS"

    def test_confidence_is_average(self) -> None:
        votes = [
            _make_vote("medication_safety", True, confidence=0.80),
            _make_vote("sdoh", True, confidence=0.90),
            _make_vote("continuity", True, confidence=1.0),
        ]
        result = _deterministic_consensus(votes, "bridge-demo-001")
        assert result.confidence == pytest.approx(0.90, abs=0.01)

    def test_synthesis_plan_merges_actions(self) -> None:
        votes = [
            _make_vote("medication_safety", False, blocking=["Pending BMP"]),
            _make_vote("sdoh", True),
            _make_vote("continuity", True),
        ]
        result = _deterministic_consensus(votes, "bridge-demo-001")
        assert isinstance(result.synthesis_plan, ConsensusPlan)
        assert result.synthesis_plan.mandatory_conditions == ["Pending BMP"]
        assert len(result.synthesis_plan.recommended_actions) >= 1


# ── TestRunClinicalDebate ─────────────────────────────────────────────────────


class TestRunClinicalDebate:
    async def test_deterministic_debate_golden_patient(
        self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle
    ) -> None:
        """Debate runs with golden patient data, no LLM."""
        result = await run_clinical_debate(golden_risk_card, golden_patient_bundle, None)
        assert isinstance(result, DebateResult)
        assert result.patient_id == golden_risk_card.patient_id
        assert result.vote_count == 3
        assert result.consensus in (
            "APPROVE", "APPROVE_WITH_CONDITIONS", "OBJECT_WITH_CONCERNS", "BLOCK"
        )

    async def test_golden_patient_has_blocking_factors(
        self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle
    ) -> None:
        """Golden patient with warfarin+pending labs should trigger objections."""
        result = await run_clinical_debate(golden_risk_card, golden_patient_bundle, None)
        # Medication safety agent should flag warfarin + pending labs
        med_vote = next(v for v in result.agent_votes if v.agent_name == "medication_safety")
        assert len(med_vote.blocking_factors) > 0 or not med_vote.approval

    async def test_all_agents_produce_valid_votes(
        self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle
    ) -> None:
        result = await run_clinical_debate(golden_risk_card, golden_patient_bundle, None)
        for vote in result.agent_votes:
            assert vote.agent_name in ("medication_safety", "sdoh", "continuity")
            assert 0.0 <= vote.confidence <= 1.0
            assert isinstance(vote.detailed_reasoning, str)
            assert len(vote.detailed_reasoning) > 0

    async def test_debate_with_minimal_patient(
        self, minimal_risk_card: RiskCard, empty_bundle: FHIRBundle
    ) -> None:
        result = await run_clinical_debate(minimal_risk_card, empty_bundle, None)
        assert isinstance(result, DebateResult)
        assert result.vote_count == 3


# ── TestIndividualAgents ──────────────────────────────────────────────────────


class TestIndividualAgents:
    async def test_medication_safety_flags_warfarin(
        self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle
    ) -> None:
        vote = await medication_safety_agent.review_discharge(
            golden_risk_card, golden_patient_bundle, None
        )
        assert vote.agent_name == "medication_safety"
        # Golden patient has warfarin — should be flagged
        assert any("warfarin" in bf.lower() or "inr" in bf.lower() for bf in vote.blocking_factors) or \
               any("warfarin" in a.lower() or "inr" in a.lower() for a in vote.suggested_actions)

    async def test_sdoh_flags_living_alone(
        self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle
    ) -> None:
        vote = await sdoh_agent.review_discharge(
            golden_risk_card, golden_patient_bundle, None
        )
        assert vote.agent_name == "sdoh"
        # Golden patient has Z60.2 living alone
        assert len(vote.blocking_factors) > 0 or "alone" in vote.primary_concern.lower()

    async def test_continuity_checks_appointments(
        self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle
    ) -> None:
        vote = await continuity_agent.review_discharge(
            golden_risk_card, golden_patient_bundle, None
        )
        assert vote.agent_name == "continuity"
        assert isinstance(vote.suggested_actions, list)

    async def test_agents_return_valid_fhir_evidence(
        self, golden_risk_card: RiskCard, golden_patient_bundle: FHIRBundle
    ) -> None:
        for agent_mod in (medication_safety_agent, sdoh_agent, continuity_agent):
            vote = await agent_mod.review_discharge(
                golden_risk_card, golden_patient_bundle, None
            )
            assert isinstance(vote.fhir_evidence, list)


# ── TestConfidenceScorer ──────────────────────────────────────────────────────


class TestConfidenceScorer:
    def test_high_risk_patient_scores_high(self, golden_risk_card: RiskCard) -> None:
        result = score_confidence(golden_risk_card, debate_approve_ratio=0.67)
        assert isinstance(result, ConfidenceExplanation)
        assert result.score > 0.5
        assert result.level in ("VERY_HIGH", "HIGH", "MODERATE", "LOW")

    def test_low_risk_scores_lower(self, minimal_risk_card: RiskCard) -> None:
        result = score_confidence(minimal_risk_card, debate_approve_ratio=1.0)
        assert result.score < score_confidence(
            RiskCard(
                patient_id="test", lace_plus_score=14, risk_level=RiskLevel.HIGH,
                primary_drivers=[], medication_flags=["warfarin"],
                sdoh_flags=["Z60.2: Living alone"], pending_labs=["BMP"],
                missing_follow_ups=[], fhir_citations=[],
            ),
            debate_approve_ratio=0.67,
        ).score

    def test_factor_attribution_sums_to_score(self, golden_risk_card: RiskCard) -> None:
        result = score_confidence(golden_risk_card, debate_approve_ratio=0.67)
        total = sum(f.weight for f in result.key_factors)
        assert abs(total - result.score) < 0.01

    def test_limitations_present(self, golden_risk_card: RiskCard) -> None:
        result = score_confidence(golden_risk_card)
        assert len(result.limitations) > 0
        assert any("synthetic" in lim.lower() for lim in result.limitations)


# ── TestReasonTrace ───────────────────────────────────────────────────────────


class TestReasonTrace:
    def test_build_trace_basic(self, golden_risk_card: RiskCard) -> None:
        trace = build_trace(
            patient_id="bridge-demo-001",
            tool_called="generate_care_plan",
            risk_card=golden_risk_card,
            reasoning_path=["sentinel_a2a", "care_plan_ai"],
            fallback_used=False,
        )
        assert isinstance(trace, ReasonTrace)
        assert trace.patient_id == "bridge-demo-001"
        assert trace.tool_called == "generate_care_plan"
        assert trace.lace_plus_score == golden_risk_card.lace_plus_score

    def test_trace_with_debate_result(
        self, golden_risk_card: RiskCard
    ) -> None:
        debate = DebateResult(
            patient_id="bridge-demo-001",
            consensus="APPROVE_WITH_CONDITIONS",
            confidence=0.84,
            vote_count=3,
            approve_count=2,
            block_count=1,
            agent_votes=[],
            dissenting_votes=[],
            synthesis_plan=ConsensusPlan(
                mandatory_conditions=["STAT BMP"],
                recommended_actions=["Home nurse"],
                monitoring_requirements=["Daily weight"],
                discharge_timeline="Within 24-48 hours",
            ),
            arbitration="Consensus reached with conditions.",
        )
        confidence = score_confidence(golden_risk_card, 0.67)
        trace = build_trace(
            patient_id="bridge-demo-001",
            tool_called="generate_care_plan",
            risk_card=golden_risk_card,
            reasoning_path=["sentinel_a2a", "care_plan_ai", "debate", "synthesis"],
            fallback_used=False,
            debate_result=debate,
            confidence=confidence,
        )
        assert trace.debate_result is not None
        assert trace.debate_result.consensus == "APPROVE_WITH_CONDITIONS"
        assert trace.confidence is not None
        assert trace.confidence.score > 0

    def test_trace_records_fallback(self, golden_risk_card: RiskCard) -> None:
        trace = build_trace(
            patient_id="bridge-demo-001",
            tool_called="generate_care_plan",
            risk_card=golden_risk_card,
            reasoning_path=["sentinel_a2a", "care_plan_deterministic"],
            fallback_used=True,
        )
        assert trace.fallback_used is True
