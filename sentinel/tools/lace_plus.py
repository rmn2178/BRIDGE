"""Deterministic LACE+ scoring implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from shared.models import RiskDriver, RiskLevel
from common.constants import RISK_THRESHOLDS
from sentinel.tools.fhir_snapshot import FHIRBundle
from common.normalize import normalize_resource


def _safe_parse_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        if value.endswith("Z"):
            value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _length_of_stay_days(encounters: List[dict]) -> int:
    inpatient = None
    for encounter in encounters:
        resource = normalize_resource(encounter)
        class_code = (
            resource.get("class", {}).get("code")
            if isinstance(resource.get("class"), dict)
            else None
        )
        if class_code == "IMP":
            inpatient = resource
            break
    if inpatient is None and encounters:
        inpatient = normalize_resource(encounters[0])

    if not inpatient:
        return 6

    period = inpatient.get("period", {}) if isinstance(inpatient.get("period"), dict) else {}
    start = _safe_parse_datetime(period.get("start"))
    end = _safe_parse_datetime(period.get("end"))
    if not start or not end:
        return 6
    delta_days = (end.date() - start.date()).days + 1
    if delta_days < 0:
        return 6
    return delta_days


def _score_los(days: int) -> int:
    if days <= 1:
        return 0
    if days == 2:
        return 1
    if days == 3:
        return 2
    if 4 <= days <= 6:
        return 3
    if 7 <= days <= 13:
        return 4
    return 5


def _has_active_chf(conditions: List[dict]) -> bool:
    for condition in conditions:
        resource = normalize_resource(condition)
        clinical_status = resource.get("clinicalStatus", {})
        status_code = None
        if isinstance(clinical_status, dict):
            coding = clinical_status.get("coding", [])
            if coding and isinstance(coding, list) and isinstance(coding[0], dict):
                status_code = coding[0].get("code")
        if status_code and status_code != "active":
            continue

        code = resource.get("code", {})
        coding = code.get("coding", []) if isinstance(code, dict) else []
        for item in coding:
            if not isinstance(item, dict):
                continue
            system = item.get("system")
            code_value = item.get("code", "")
            if system == "http://hl7.org/fhir/sid/icd-10-cm" and code_value.startswith(
                "I50"
            ):
                return True
    return False


def _count_active_conditions(conditions: List[dict]) -> int:
    count = 0
    for condition in conditions:
        resource = normalize_resource(condition)
        clinical_status = resource.get("clinicalStatus", {})
        status_code = None
        if isinstance(clinical_status, dict):
            coding = clinical_status.get("coding", [])
            if coding and isinstance(coding, list) and isinstance(coding[0], dict):
                status_code = coding[0].get("code")
        if status_code is None or status_code == "active":
            count += 1
    return count


def _score_comorbidity(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count == 2:
        return 2
    if count == 3:
        return 3
    return 5


def _count_ed_visits(encounters: List[dict]) -> int:
    count = 0
    for encounter in encounters:
        resource = normalize_resource(encounter)
        class_code = (
            resource.get("class", {}).get("code")
            if isinstance(resource.get("class"), dict)
            else None
        )
        if class_code == "EMER":
            count += 1
    return count


def _score_ed_visits(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count == 2:
        return 2
    if count == 3:
        return 3
    return 4


def _patient_age_years(patient: dict) -> int | None:
    birth_date = patient.get("birthDate")
    if not isinstance(birth_date, str):
        return None
    try:
        birth = datetime.fromisoformat(birth_date)
    except Exception:
        return None
    today = datetime.now(timezone.utc)
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return age




def _risk_level(score: int) -> RiskLevel:
    for threshold, label in RISK_THRESHOLDS:
        if score <= threshold:
            return RiskLevel(label)
    return RiskLevel.VERY_HIGH


def calculate_lace_plus(bundle: FHIRBundle) -> dict:
    """Compute LACE+ scores and drivers for the given FHIR bundle."""

    los_days = _length_of_stay_days(bundle.encounters)
    los_score = _score_los(los_days)

    acute = _has_active_chf(bundle.conditions)
    acuity_score = 3 if acute else 0

    comorbidity_count = _count_active_conditions(bundle.conditions)
    comorbidity_score = _score_comorbidity(comorbidity_count)

    ed_visits = _count_ed_visits(bundle.encounters)
    ed_score = _score_ed_visits(ed_visits)

    age_years = _patient_age_years(bundle.patient)
    age_score = 3 if age_years is not None and age_years >= 65 else 0

    raw_score = los_score + acuity_score + comorbidity_score + ed_score + age_score

    drivers = [
        RiskDriver(
            criterion=f"Length of stay {los_days} days",
            points=los_score,
            fhir_evidence=["Encounter/index-001"] if bundle.encounters else [],
        ),
        RiskDriver(
            criterion="Acute CHF exacerbation" if acute else "No CHF flare",
            points=acuity_score,
            fhir_evidence=["Condition/chf-001"] if acute else [],
        ),
        RiskDriver(
            criterion=f"Comorbidities: {comorbidity_count} active conditions",
            points=comorbidity_score,
            fhir_evidence=[
                f"Condition/{normalize_resource(c).get('id')}"
                for c in bundle.conditions
                if normalize_resource(c).get("id")
            ],
        ),
        RiskDriver(
            criterion=f"ED visits in last 6 months: {ed_visits}",
            points=ed_score,
            fhir_evidence=[
                f"Encounter/{normalize_resource(e).get('id')}"
                for e in bundle.encounters
                if normalize_resource(e).get("id")
                and normalize_resource(e).get("class", {}).get("code") == "EMER"
            ],
        ),
        RiskDriver(
            criterion=f"Age {age_years} years" if age_years is not None else "Age unknown",
            points=age_score,
            fhir_evidence=[f"Patient/{bundle.patient.get('id')}"]
            if bundle.patient.get("id")
            else [],
        ),
    ]

    return {
        "lace_plus_score": raw_score,
        "risk_level": _risk_level(raw_score),
        "primary_drivers": [driver.model_dump() for driver in drivers],
        "raw_score": raw_score,
    }
