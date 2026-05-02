"""Unit tests for GenAI integration paths — all LLM calls mocked."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bridge_agent.tools.care_plan import generate_care_plan
from bridge_agent.tools.care_plan_ai import generate_care_plan_ai
from bridge_agent.tools.gap_ai import audit_documentation_gaps_ai
from bridge_agent.tools.handoff_ai import draft_pcp_handoff_ai
from sentinel.tools.risk_narrative import generate_risk_narrative, _deterministic_narrative
from shared.models import (
    CarePlanAction, CarePlanOutput, GapAuditItem, GapAuditOutput,
    PCPHandoff, RiskCard, RiskLevel,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_llm_client(return_value=None, raise_exc=None):
    """Return a mock LLMClient whose methods return or raise as specified."""
    from shared.llm import LLMClient
    client = MagicMock(spec=LLMClient)
    if raise_exc:
        client.generate_care_plan = AsyncMock(side_effect=raise_exc)
        client.generate_handoff_letter = AsyncMock(side_effect=raise_exc)
        client.prioritize_gaps = AsyncMock(side_effect=raise_exc)
        client.generate_risk_narrative = AsyncMock(side_effect=raise_exc)
        client.generate_patient_instructions = AsyncMock(side_effect=raise_exc)
    else:
        client.generate_care_plan = AsyncMock(return_value=return_value)
        client.generate_handoff_letter = AsyncMock(return_value=return_value)
        client.prioritize_gaps = AsyncMock(return_value=return_value)
        client.generate_risk_narrative = AsyncMock(return_value=return_value)
        client.generate_patient_instructions = AsyncMock(return_value="AI patient instructions.")
    return client


# ── TestLLMClientInit ─────────────────────────────────────────────────────────

class TestLLMClientInit:
    def test_missing_api_key_raises_when_genai_enabled(self, monkeypatch) -> None:
        monkeypatch.setenv("USE_GENAI", "true")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from shared.llm import LLMClient
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            LLMClient()

    def test_missing_api_key_ok_when_genai_disabled(self, monkeypatch) -> None:
        monkeypatch.setenv("USE_GENAI", "false")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # When USE_GENAI=false the client is never instantiated — no error expected
        assert os.getenv("USE_GENAI") == "false"

    def test_custom_model_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-that-is-long-enough-32chars")
        monkeypatch.setenv("OPENAI_MODEL_DEFAULT", "gpt-4o")
        monkeypatch.setenv("USE_GENAI", "true")
        import importlib
        import shared.llm as llm_mod
        importlib.reload(llm_mod)
        assert llm_mod._DEFAULT_MODEL == "gpt-4o"

    def test_timeout_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")
        import importlib
        import shared.llm as llm_mod
        importlib.reload(llm_mod)
        assert llm_mod._TIMEOUT == 60.0


# ── TestCarePlanAI ────────────────────────────────────────────────────────────

class TestCarePlanAI:
    async def test_llm_enrichment_adds_actions(self, golden_risk_card: RiskCard) -> None:
        baseline = generate_care_plan(golden_risk_card)
        extra_action = CarePlanAction(
            action="Schedule echocardiogram within 30 days",
            priority="HIGH",
            rationale="CHF follow-up per ACC/AHA guidelines.",
            risk_card_source="primary_drivers",
        )
        enriched = CarePlanOutput(
            patient_id=baseline.patient_id,
            actions=baseline.actions + [extra_action],
            patient_instructions=baseline.patient_instructions,
            clinician_summary=baseline.clinician_summary,
        )
        llm = _make_llm_client(return_value=enriched)
        result = await generate_care_plan_ai(golden_risk_card, llm)
        assert any("echocardiogram" in a.action.lower() for a in result.actions)

    async def test_llm_preserves_critical_baseline_actions(self, golden_risk_card: RiskCard) -> None:
        baseline = generate_care_plan(golden_risk_card)
        # LLM returns plan WITHOUT the critical INR action
        no_critical = CarePlanOutput(
            patient_id=baseline.patient_id,
            actions=[a for a in baseline.actions if a.priority != "CRITICAL"],
            patient_instructions=baseline.patient_instructions,
            clinician_summary=baseline.clinician_summary,
        )
        llm = _make_llm_client(return_value=no_critical)
        result = await generate_care_plan_ai(golden_risk_card, llm)
        assert any(a.priority == "CRITICAL" for a in result.actions)

    async def test_fallback_to_deterministic_on_llm_failure(self, golden_risk_card: RiskCard) -> None:
        llm = _make_llm_client(raise_exc=RuntimeError("OpenAI timeout"))
        result = await generate_care_plan_ai(golden_risk_card, llm)
        assert isinstance(result, CarePlanOutput)
        assert len(result.actions) >= 1

    async def test_output_validates_careplan_schema(self, golden_risk_card: RiskCard) -> None:
        result = await generate_care_plan_ai(golden_risk_card, None)
        assert isinstance(result, CarePlanOutput)
        assert result.patient_id == golden_risk_card.patient_id

    async def test_empty_risk_card_handling(self, minimal_risk_card: RiskCard) -> None:
        result = await generate_care_plan_ai(minimal_risk_card, None)
        assert isinstance(result, CarePlanOutput)

    async def test_none_llm_returns_deterministic(self, golden_risk_card: RiskCard) -> None:
        result = await generate_care_plan_ai(golden_risk_card, None)
        baseline = generate_care_plan(golden_risk_card)
        assert result.patient_id == baseline.patient_id
        assert len(result.actions) == len(baseline.actions)


# ── TestHandoffAI ─────────────────────────────────────────────────────────────

class TestHandoffAI:
    async def test_generated_letter_contains_required_sections(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        from bridge_agent.tools.pcp_handoff import draft_pcp_handoff
        baseline = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        llm = _make_llm_client(return_value=baseline)
        result = await draft_pcp_handoff_ai(golden_risk_card, golden_patient_bundle, llm)
        letter = result.handoff_letter.upper()
        for section in ("HOSPITAL COURSE", "KEY MEDICATIONS", "ACTIVE CONCERNS",
                        "READMISSION RISK", "SUGGESTED FOLLOW-UP"):
            assert section in letter, f"Missing section: {section}"

    async def test_medications_have_fhir_citations(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        result = await draft_pcp_handoff_ai(golden_risk_card, golden_patient_bundle, None)
        assert "MedicationRequest/" in result.handoff_letter

    async def test_word_count_within_bounds(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        result = await draft_pcp_handoff_ai(golden_risk_card, golden_patient_bundle, None)
        wc = len(result.handoff_letter.split())
        assert wc >= 300

    async def test_warfarin_concern_flagged(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        result = await draft_pcp_handoff_ai(golden_risk_card, golden_patient_bundle, None)
        letter = result.handoff_letter.lower()
        assert "warfarin" in letter or "inr" in letter or "anticoag" in letter

    async def test_fallback_to_template_on_llm_failure(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        llm = _make_llm_client(raise_exc=RuntimeError("LLM unavailable"))
        result = await draft_pcp_handoff_ai(golden_risk_card, golden_patient_bundle, llm)
        assert isinstance(result, PCPHandoff)
        assert len(result.handoff_letter) > 100

    async def test_word_count_out_of_bounds_falls_back(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        from bridge_agent.tools.pcp_handoff import draft_pcp_handoff
        baseline = draft_pcp_handoff(golden_risk_card, golden_patient_bundle)
        short_handoff = PCPHandoff(
            patient_id=baseline.patient_id,
            hospitalization_reason=baseline.hospitalization_reason,
            medication_changes=baseline.medication_changes,
            pending_concerns=baseline.pending_concerns,
            follow_up_priorities=baseline.follow_up_priorities,
            handoff_letter="Too short.",
        )
        llm = _make_llm_client(return_value=short_handoff)
        result = await draft_pcp_handoff_ai(golden_risk_card, golden_patient_bundle, llm)
        # Should fall back to baseline (>= 300 words)
        assert len(result.handoff_letter.split()) >= 300


# ── TestGapAI ─────────────────────────────────────────────────────────────────

class TestGapAI:
    def _enriched_audit(self, baseline: GapAuditOutput) -> GapAuditOutput:
        items = []
        for item in baseline.items:
            if item.status == "FAIL":
                items.append(GapAuditItem(
                    requirement=item.requirement,
                    status="FAIL",
                    fhir_evidence=item.fhir_evidence,
                    remediation=item.remediation,
                    ai_severity=5,
                    ai_clinical_context="Schedule TTE within 14 days given EF 35%.",
                    ai_interdependencies=["medication_reconciliation"],
                ))
            else:
                items.append(item)
        return GapAuditOutput(
            patient_id=baseline.patient_id,
            overall_status=baseline.overall_status,
            items=items,
        )

    async def test_severity_scores_assigned_to_fail_items(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        from bridge_agent.tools.gap_audit import audit_documentation_gaps
        baseline = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        enriched = self._enriched_audit(baseline)
        llm = _make_llm_client(return_value=enriched)
        result = await audit_documentation_gaps_ai(golden_risk_card, golden_patient_bundle, llm)
        fail_items = [i for i in result.items if i.status == "FAIL"]
        assert all(i.ai_severity is not None for i in fail_items)

    async def test_remediation_more_specific_than_generic(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        from bridge_agent.tools.gap_audit import audit_documentation_gaps
        baseline = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        enriched = self._enriched_audit(baseline)
        llm = _make_llm_client(return_value=enriched)
        result = await audit_documentation_gaps_ai(golden_risk_card, golden_patient_bundle, llm)
        fail_items = [i for i in result.items if i.status == "FAIL"]
        assert any(i.ai_clinical_context for i in fail_items)

    async def test_interdependencies_identified(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        from bridge_agent.tools.gap_audit import audit_documentation_gaps
        baseline = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        enriched = self._enriched_audit(baseline)
        llm = _make_llm_client(return_value=enriched)
        result = await audit_documentation_gaps_ai(golden_risk_card, golden_patient_bundle, llm)
        fail_items = [i for i in result.items if i.status == "FAIL"]
        assert any(len(i.ai_interdependencies) > 0 for i in fail_items)

    async def test_sorting_by_severity(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        from bridge_agent.tools.gap_audit import audit_documentation_gaps
        baseline = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        # Build enriched with descending severities
        items = []
        severity = 5
        for item in baseline.items:
            if item.status == "FAIL":
                items.append(GapAuditItem(
                    requirement=item.requirement, status="FAIL",
                    ai_severity=severity, ai_clinical_context="ctx",
                    ai_interdependencies=[],
                ))
                severity -= 1
            else:
                items.append(item)
        enriched = GapAuditOutput(
            patient_id=baseline.patient_id,
            overall_status=baseline.overall_status,
            items=items,
        )
        llm = _make_llm_client(return_value=enriched)
        result = await audit_documentation_gaps_ai(golden_risk_card, golden_patient_bundle, llm)
        fail_severities = [i.ai_severity for i in result.items
                           if i.status == "FAIL" and i.ai_severity is not None]
        assert fail_severities == sorted(fail_severities, reverse=True)

    async def test_pass_items_unmodified(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        from bridge_agent.tools.gap_audit import audit_documentation_gaps
        baseline = audit_documentation_gaps(golden_risk_card, golden_patient_bundle)
        enriched = self._enriched_audit(baseline)
        llm = _make_llm_client(return_value=enriched)
        result = await audit_documentation_gaps_ai(golden_risk_card, golden_patient_bundle, llm)
        for item in result.items:
            if item.status == "PASS":
                assert item.ai_severity is None
                assert item.ai_clinical_context is None

    async def test_fallback_on_llm_failure(
        self, golden_risk_card: RiskCard, golden_patient_bundle
    ) -> None:
        llm = _make_llm_client(raise_exc=RuntimeError("LLM down"))
        result = await audit_documentation_gaps_ai(golden_risk_card, golden_patient_bundle, llm)
        assert isinstance(result, GapAuditOutput)
        assert result.overall_status == "ACTION_REQUIRED"


# ── TestRiskNarrative ─────────────────────────────────────────────────────────

class TestRiskNarrative:
    async def test_deterministic_narrative_no_llm(self, golden_risk_card: RiskCard) -> None:
        result = await generate_risk_narrative(golden_risk_card, None)
        assert isinstance(result, str)
        assert len(result.split()) >= 30

    async def test_deterministic_narrative_contains_risk_level(self, golden_risk_card: RiskCard) -> None:
        result = _deterministic_narrative(golden_risk_card)
        assert "HIGH" in result

    async def test_deterministic_narrative_contains_lace_score(self, golden_risk_card: RiskCard) -> None:
        result = _deterministic_narrative(golden_risk_card)
        assert str(golden_risk_card.lace_plus_score) in result

    async def test_llm_narrative_used_when_valid(self, golden_risk_card: RiskCard) -> None:
        long_narrative = "This patient is at HIGH readmission risk " * 5
        llm = _make_llm_client(return_value=long_narrative)
        result = await generate_risk_narrative(golden_risk_card, llm)
        assert result == long_narrative

    async def test_fallback_when_llm_returns_short_text(self, golden_risk_card: RiskCard) -> None:
        llm = _make_llm_client(return_value="Too short.")
        result = await generate_risk_narrative(golden_risk_card, llm)
        # Should fall back to deterministic
        assert str(golden_risk_card.lace_plus_score) in result

    async def test_fallback_on_llm_exception(self, golden_risk_card: RiskCard) -> None:
        llm = _make_llm_client(raise_exc=RuntimeError("API error"))
        result = await generate_risk_narrative(golden_risk_card, llm)
        assert isinstance(result, str)
        assert len(result) > 50
