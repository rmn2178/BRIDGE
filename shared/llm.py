"""Centralized LLM client with retry, fallback, and structured output enforcement."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Awaitable, Literal, Optional, TypeVar

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from shared.models import CarePlanOutput, GapAuditOutput, PCPHandoff, RiskCard, DebateResult, ConsensusPlan
from sentinel.tools.fhir_snapshot import FHIRBundle

_logger = structlog.get_logger("bridge.llm")

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

T = TypeVar("T")

_USE_GENAI = os.getenv("USE_GENAI", "true").lower() == "true"
_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
_DEFAULT_MODEL = os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini")
_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _care_plan_system_prompt() -> str:
    base = _load_prompt("care_plan.txt")
    return base or (
        "You are BRIDGE Care Plan Generator, a clinical discharge planning assistant. "
        "Output strict JSON matching CarePlanOutput schema. "
        "SAFETY RAILS: Never invent clinical data. Cite FHIR IDs in rationale. "
        "Never remove CRITICAL priority items from the baseline. "
        "If uncertain, omit rather than hallucinate."
    )


def _handoff_system_prompt() -> str:
    base = _load_prompt("pcp_handoff.txt")
    return base or (
        "You are BRIDGE PCP Handoff Drafter. Output strict JSON matching PCPHandoff schema. "
        "Every medication claim MUST include [FHIR: MedicationRequest/ID]. "
        "If warfarin is active and no INR follow-up scheduled, flag as CONCERN #1. "
        "handoff_letter must be 300-600 words. Clinical, concise, no unsupported claims."
    )


def _gap_system_prompt() -> str:
    return (
        "You are BRIDGE Gap Audit Prioritizer. Output strict JSON matching GapAuditOutput schema. "
        "For each FAIL item add: ai_severity (1-5, 5=most critical), ai_clinical_context "
        "(specific actionable guidance, not generic), ai_interdependencies (list of related gaps). "
        "Sort FAIL items by ai_severity descending. PASS items must remain unmodified. "
        "Never invent gaps not in the input."
    )


def _narrative_system_prompt() -> str:
    return (
        "You are BRIDGE Risk Narrative Generator. Write a single plain-language paragraph "
        "(~100 words) summarising the patient's readmission risk. "
        "Include: LACE+ score, risk level, top 2 clinical drivers, key medication/SDoH flags, "
        "and the single most important priority action. "
        "Tone: clear enough for a patient advocate, precise enough for a clinician. "
        "Never invent data not in the RiskCard."
    )


def _patient_instructions_system_prompt(reading_level: str) -> str:
    base = _load_prompt("patient_instructions.txt")
    level_map = {"5th": "5th-grade", "8th": "8th-grade", "12th": "12th-grade"}
    level_text = level_map.get(reading_level, "6th-grade")
    if base:
        return base.replace("6th-grade", level_text)
    return (
        f"You are BRIDGE Patient Instructions Assistant. Write one paragraph at {level_text} "
        "reading level. Include: medication adherence, weight monitoring trigger, home nurse "
        "visit if present, follow-up scheduling, and when to call 911. No medical jargon. "
        "Use only facts from the RiskCard."
    )


class LLMClient:
    """Async LLM client with retry, structured output, and deterministic fallback."""

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if _USE_GENAI and not api_key:
            raise ValueError("OPENAI_API_KEY is required when USE_GENAI=true")
        if _PROVIDER == "openai":
            from openai import AsyncOpenAI
            self._client: Any = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT)
        else:
            # Ollama / local: point base_url at local server, no key needed
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key="ollama",
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                timeout=_TIMEOUT,
            )
        self._model = _DEFAULT_MODEL

    # ── Internal retry-wrapped chat call ─────────────────────────────────────

    @retry(
        stop=stop_after_attempt(_MAX_RETRIES),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def _chat(self, system: str, user: str, model: str, temperature: float) -> str:
        response = await self._client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        _logger.info(
            "llm_call_complete",
            model=model,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
        )
        return content

    # ── Safe wrapper with deterministic fallback ──────────────────────────────

    async def _safe(
        self,
        llm_coro: Awaitable[T],
        fallback_fn: Callable[[], T],
        label: str,
    ) -> T:
        try:
            result = await llm_coro
            return result
        except Exception as exc:
            _logger.warning("llm_fallback_triggered", label=label, error=str(exc),
                            fallback=fallback_fn.__name__)
            return fallback_fn()

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate_care_plan(
        self,
        risk_card: RiskCard,
        baseline: CarePlanOutput,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.3,
    ) -> CarePlanOutput:
        system = _care_plan_system_prompt()
        user = json.dumps({
            "patient_summary": {
                "patient_id": risk_card.patient_id,
                "lace_plus_score": risk_card.lace_plus_score,
                "risk_level": risk_card.risk_level.value,
                "medication_flags": risk_card.medication_flags,
                "sdoh_flags": risk_card.sdoh_flags,
                "pending_labs": risk_card.pending_labs,
                "missing_follow_ups": risk_card.missing_follow_ups,
            },
            "fhir_evidence": risk_card.fhir_citations,
            "baseline_actions": [a.model_dump() for a in baseline.actions],
            "instruction": (
                "Enrich the baseline actions with additional clinically-relevant actions. "
                "Never remove CRITICAL baseline actions. Merge and deduplicate by action text. "
                "Return the full CarePlanOutput JSON."
            ),
        })

        async def _call() -> CarePlanOutput:
            raw = await self._chat(system, user, model, temperature)
            data = json.loads(raw)
            # Ensure baseline CRITICAL actions are never dropped
            result = CarePlanOutput.model_validate(data)
            baseline_critical = {a.action for a in baseline.actions if a.priority == "CRITICAL"}
            result_actions = {a.action for a in result.actions}
            missing = baseline_critical - result_actions
            if missing:
                for a in baseline.actions:
                    if a.action in missing:
                        result.actions.insert(0, a)
            return result

        return await self._safe(_call(), lambda: baseline, "generate_care_plan")

    async def generate_handoff_letter(
        self,
        risk_card: RiskCard,
        fhir_bundle: FHIRBundle,
        baseline: PCPHandoff,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.4,
    ) -> PCPHandoff:
        system = _handoff_system_prompt()
        med_list = [
            {"id": m.get("id"), "name": m.get("medicationCodeableConcept", {}).get("text", ""),
             "dose": (m.get("dosageInstruction") or [{}])[0].get("text", "")}
            for m in fhir_bundle.medications
            if m.get("status") == "active"
        ]
        user = json.dumps({
            "patient_id": risk_card.patient_id,
            "risk_summary": {
                "lace_plus_score": risk_card.lace_plus_score,
                "risk_level": risk_card.risk_level.value,
                "medication_flags": risk_card.medication_flags,
                "sdoh_flags": risk_card.sdoh_flags,
                "pending_labs": risk_card.pending_labs,
                "missing_follow_ups": risk_card.missing_follow_ups,
            },
            "fhir_medications": med_list,
            "fhir_citations": risk_card.fhir_citations,
            "hospitalization_reason": baseline.hospitalization_reason,
            "instruction": (
                "Generate a PCPHandoff JSON. The handoff_letter must be 300-600 words, "
                "include all required sections, and cite every medication with its FHIR ID."
            ),
        })

        async def _call() -> PCPHandoff:
            raw = await self._chat(system, user, model, temperature)
            return PCPHandoff.model_validate(json.loads(raw))

        return await self._safe(_call(), lambda: baseline, "generate_handoff_letter")

    async def generate_patient_instructions(
        self,
        risk_card: RiskCard,
        reading_level: Literal["5th", "8th", "12th"] = "8th",
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.4,
    ) -> str:
        system = _patient_instructions_system_prompt(reading_level)
        user = json.dumps({
            "patient_id": risk_card.patient_id,
            "risk_level": risk_card.risk_level.value,
            "medication_flags": risk_card.medication_flags,
            "sdoh_flags": risk_card.sdoh_flags,
            "missing_follow_ups": risk_card.missing_follow_ups,
            "pending_labs": risk_card.pending_labs,
            "instruction": "Return JSON with key: patient_instructions (string, one paragraph).",
        })

        async def _call() -> str:
            raw = await self._chat(system, user, model, temperature)
            return json.loads(raw).get("patient_instructions", "")

        fallback_text = (
            "Take your medicines exactly as prescribed. Weigh yourself every morning and "
            "call your doctor if you gain more than 2 pounds in a day or 5 pounds in a week. "
            "Keep all follow-up appointments. Call 911 for chest pain or severe trouble breathing."
        )
        return await self._safe(_call(), lambda: fallback_text, "generate_patient_instructions")

    async def prioritize_gaps(
        self,
        gap_audit: GapAuditOutput,
        risk_card: RiskCard,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.2,
    ) -> GapAuditOutput:
        system = _gap_system_prompt()
        user = json.dumps({
            "patient_id": gap_audit.patient_id,
            "risk_context": {
                "lace_plus_score": risk_card.lace_plus_score,
                "risk_level": risk_card.risk_level.value,
                "medication_flags": risk_card.medication_flags,
            },
            "gap_items": [i.model_dump() for i in gap_audit.items],
            "instruction": (
                "Return GapAuditOutput JSON. Enrich each FAIL item with ai_severity, "
                "ai_clinical_context, ai_interdependencies. Sort FAIL items by ai_severity desc. "
                "PASS items must be returned unmodified."
            ),
        })

        async def _call() -> GapAuditOutput:
            raw = await self._chat(system, user, model, temperature)
            return GapAuditOutput.model_validate(json.loads(raw))

        return await self._safe(_call(), lambda: gap_audit, "prioritize_gaps")

    async def generate_risk_narrative(
        self,
        risk_card: RiskCard,
        model: str = _DEFAULT_MODEL,
        temperature: float = 0.5,
    ) -> str:
        system = _narrative_system_prompt()
        user = json.dumps({
            "patient_id": risk_card.patient_id,
            "lace_plus_score": risk_card.lace_plus_score,
            "risk_level": risk_card.risk_level.value,
            "primary_drivers": [d.model_dump() for d in risk_card.primary_drivers],
            "medication_flags": risk_card.medication_flags,
            "sdoh_flags": risk_card.sdoh_flags,
            "missing_follow_ups": risk_card.missing_follow_ups,
            "instruction": "Return JSON with key: narrative (string, ~100 words).",
        })

        async def _call() -> str:
            raw = await self._chat(system, user, model, temperature)
            return json.loads(raw).get("narrative", "")

        fallback = (
            f"This patient is at {risk_card.risk_level.value} readmission risk "
            f"(LACE+ {risk_card.lace_plus_score}). "
            f"Key drivers: {', '.join(d.criterion for d in risk_card.primary_drivers[:2])}. "
            f"Priority: immediate follow-up and medication monitoring."
        )
        return await self._safe(_call(), lambda: fallback, "generate_risk_narrative")

    async def run_debate(
        self,
        risk_card: RiskCard,
        bundle: object,
        model: str = _DEFAULT_MODEL,
    ) -> DebateResult:
        """Convenience wrapper — delegates to debate_ai orchestrator."""
        from bridge_agent.tools.debate_ai import run_clinical_debate
        return await run_clinical_debate(risk_card, bundle, self)
