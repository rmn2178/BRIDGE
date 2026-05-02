"""AI-prioritized gap audit: deterministic checks + LLM severity scoring."""

from __future__ import annotations

from typing import Optional

import structlog

from bridge_agent.tools.gap_audit import audit_documentation_gaps
from sentinel.tools.fhir_snapshot import FHIRBundle
from shared.models import GapAuditOutput, RiskCard

_logger = structlog.get_logger("bridge.gap_ai")


async def audit_documentation_gaps_ai(
    risk_card: RiskCard,
    bundle: FHIRBundle,
    llm_client: Optional[object] = None,
) -> GapAuditOutput:
    """Run deterministic gap audit then enrich FAIL items with AI severity + context.

    Falls back to deterministic-only if llm_client is None or LLM fails.
    PASS items are never modified.
    """
    baseline = audit_documentation_gaps(risk_card, bundle)

    if llm_client is None:
        return baseline

    from shared.llm import LLMClient
    if not isinstance(llm_client, LLMClient):
        return baseline

    try:
        enriched = await llm_client.prioritize_gaps(baseline, risk_card)
    except Exception as exc:
        _logger.warning("gap_ai_fallback", error=str(exc), patient_id=risk_card.patient_id)
        return baseline

    # Safety: ensure PASS items were not modified
    baseline_pass = {i.requirement: i for i in baseline.items if i.status == "PASS"}
    for item in enriched.items:
        if item.status == "PASS" and item.requirement in baseline_pass:
            orig = baseline_pass[item.requirement]
            item.fhir_evidence = orig.fhir_evidence
            item.remediation = orig.remediation

    _logger.info(
        "gap_ai_complete",
        patient_id=risk_card.patient_id,
        fail_items=sum(1 for i in enriched.items if i.status == "FAIL"),
        ai_enriched=True,
    )
    return enriched
