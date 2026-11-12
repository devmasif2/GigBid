"""Deterministic safety baseline for explicit job risk signals."""

import re
from typing import Any

from agent.handoffs import RiskReport

_RISK_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    (
        "unpaid_production_work",
        re.compile(
            r"\b(unpaid|for free|without pay|free)\b.{0,50}\b(trial|test|production|dashboard|project|work)\b",
            re.IGNORECASE,
        ),
        0.8,
    ),
    (
        "off_platform_contact",
        re.compile(
            r"\b(whatsapp|telegram|external messaging|outside the platform|off[- ]platform)\b",
            re.IGNORECASE,
        ),
        0.9,
    ),
    (
        "off_platform_payment",
        re.compile(
            r"\b(pay|payment|transfer)\b.{0,30}\b(crypto|paypal|outside|off[- ]platform)\b",
            re.IGNORECASE,
        ),
        0.9,
    ),
    (
        "prompt_injection",
        re.compile(
            r"\b(ignore (all )?(previous|prior|system) instructions|reveal (the )?(system prompt|secrets)|override (all )?policies)\b",
            re.IGNORECASE,
        ),
        0.8,
    ),
    (
        "guaranteed_results",
        re.compile(
            r"\b(?:guarantee|guaranteed)\b.{0,45}"
            r"\b(?:100\s*%\s*(?:accuracy|success|results?)|first[- ]page ranking)\b",
            re.IGNORECASE,
        ),
        0.8,
    ),
)

_FLAG_SCORES = {
    "unpaid_work": ("unpaid_production_work", 0.8),
    "off_platform_contact": ("off_platform_contact", 0.9),
    "off_platform_payment": ("off_platform_payment", 0.9),
    "prompt_injection": ("prompt_injection", 0.8),
    "guaranteed_results": ("guaranteed_results", 0.8),
}


def assess_risk(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    job = state.get("job")
    if job is None:
        raise ValueError("state must contain a job object")
    if not isinstance(job, dict):
        raise TypeError("job must be an object")

    text_parts = [job.get("title", ""), job.get("description", "")]
    if not all(isinstance(part, str) for part in text_parts):
        raise TypeError("job title and description must be strings")
    text = " ".join(text_parts)
    detected: dict[str, float] = {}
    reasons: list[str] = []

    for flag, pattern, score in _RISK_PATTERNS:
        if pattern.search(text):
            detected[flag] = score

    warning_signals = job.get("warning_signals", [])
    if not isinstance(warning_signals, list):
        raise TypeError("job.warning_signals must be a list")
    for signal in warning_signals:
        if not isinstance(signal, str):
            continue
        mapped = _FLAG_SCORES.get(signal.casefold())
        if mapped is not None:
            flag, score = mapped
            detected[flag] = max(score, detected.get(flag, 0))
        else:
            detected[f"reported:{signal}"] = 0.5

    history = state.get("client_history")
    if history is not None:
        if not isinstance(history, dict):
            raise TypeError("client_history must be an object")
        if not history["payment_verified"]:
            detected["unverified_payment"] = 0.4
        if history["jobs_posted"] >= 5 and history["hire_rate"] < 0.2:
            detected["low_hire_rate"] = 0.4
        if history["average_rating"] is not None and history["average_rating"] < 3.5:
            detected["low_client_rating"] = 0.5

    if detected:
        reasons.extend(f"{flag.replace('_', ' ')} detected" for flag in detected)
        score = max(detected.values())
        explanation = "Potential risk signals require human review: " + "; ".join(reasons)
    else:
        score = 0.0
        explanation = "No configured risk signals were detected; this is not a safety guarantee."

    if history is None:
        explanation += " Client history was not available for this assessment."

    report = RiskReport(score=score, flags=list(detected), explanation=explanation)
    return {"risk_report": report.model_dump(mode="json")}
