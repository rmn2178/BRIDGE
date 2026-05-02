"""Confidence scorer — attribution analysis for care plan outputs."""

from __future__ import annotations

from typing import Dict

from shared.models import ConfidenceExplanation, ConfidenceFactor, RiskCard


def score_confidence(risk_card: RiskCard, debate_approve_ratio: float = 1.0) -> ConfidenceExplanation:
    """Compute a weighted confidence score with factor attribution.

    Weights are deterministic and clinically motivated — no LLM required.
    """
    factors: list[ConfidenceFactor] = []
    total = 0.0

    # LACE+ score contribution (max 0.45)
    lace_weight = min(risk_card.lace_plus_score / 19.0 * 0.45, 0.45)
    factors.append(ConfidenceFactor(
        factor=f"LACE+ score {risk_card.lace_plus_score}/19",
        weight=round(lace_weight, 3),
        certainty="Certain",
    ))
    total += lace_weight

    # High-risk medication flags (max 0.20)
    if risk_card.medication_flags:
        med_weight = min(len(risk_card.medication_flags) * 0.10, 0.20)
        factors.append(ConfidenceFactor(
            factor=f"High-risk medications: {', '.join(risk_card.medication_flags[:2])}",
            weight=round(med_weight, 3),
            certainty="Certain",
        ))
        total += med_weight

    # SDoH flags (max 0.15)
    if risk_card.sdoh_flags:
        sdoh_weight = min(len(risk_card.sdoh_flags) * 0.075, 0.15)
        factors.append(ConfidenceFactor(
            factor=f"SDoH barriers: {risk_card.sdoh_flags[0].split(':')[0]}",
            weight=round(sdoh_weight, 3),
            certainty="Moderate",
        ))
        total += sdoh_weight

    # Agent consensus contribution (max 0.20)
    consensus_weight = round(debate_approve_ratio * 0.20, 3)
    factors.append(ConfidenceFactor(
        factor=f"Agent consensus ({int(debate_approve_ratio * 100)}% approval)",
        weight=consensus_weight,
        certainty="High" if debate_approve_ratio >= 0.67 else "Moderate",
    ))
    total += consensus_weight

    score = round(min(total, 1.0), 3)

    if score >= 0.80:
        level = "VERY_HIGH"
    elif score >= 0.65:
        level = "HIGH"
    elif score >= 0.45:
        level = "MODERATE"
    else:
        level = "LOW"

    return ConfidenceExplanation(
        score=score,
        level=level,
        key_factors=sorted(factors, key=lambda f: f.weight, reverse=True),
        limitations=[
            "Based on synthetic demo data only",
            "Real deployment requires validation against historical readmission cohort",
            "Confidence weights are illustrative — not clinically validated thresholds",
        ],
    )
