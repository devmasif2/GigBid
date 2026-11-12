"""Final deterministic policy checks before a draft can be shown for approval."""

import re
from typing import Any

from agent.handoffs import ComplianceVerdict
from agent.nodes.writer import SCREENING_PLACEHOLDER

MISSING_ANSWERS_REASON = "All screening questions require non-placeholder answers."

_BLOCK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "contact_details",
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b|\b(?:\+?\d[\d ()-]{7,}\d)\b"),
    ),
    (
        "guarantee",
        re.compile(r"\b(guarantee|guaranteed|100%\s*(?:success|results?))\b", re.IGNORECASE),
    ),
    (
        "off_platform",
        re.compile(
            r"\b(whatsapp|telegram|outside the platform|off[- ]platform payment)\b",
            re.IGNORECASE,
        ),
    ),
)


def prohibited_text_reasons(text: str) -> list[str]:
    return [
        f"Draft contains prohibited {name.replace('_', ' ')}."
        for name, pattern in _BLOCK_PATTERNS
        if pattern.search(text)
    ]


def check_compliance(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    draft = state.get("proposal_draft")
    critique = state.get("critique")
    verification = state.get("claim_verification", [])
    if draft is None or critique is None:
        raise ValueError("state must contain proposal_draft and critique")
    if not isinstance(draft, dict) or not isinstance(critique, dict):
        raise TypeError("proposal_draft and critique must be objects")

    text = " ".join(
        [draft.get("cover_letter", ""), *draft.get("screening_answers", [])]
    )
    reasons = prohibited_text_reasons(text)
    if critique.get("passed") is not True:
        reasons.append("Critic did not approve the draft structure.")
    for claim in verification:
        if isinstance(claim, dict) and claim.get("status") == "unsupported":
            reasons.append("Draft contains an unsupported portfolio claim.")
            break

    policy = state.get("marketplace_policy")
    if policy is not None:
        if len(draft["cover_letter"]) > policy["max_cover_letter_chars"]:
            reasons.append("Cover letter exceeds the current marketplace limit.")
        if any(phrase.casefold() in text.casefold() for phrase in policy["banned_phrases"]):
            reasons.append("Draft contains a phrase banned by the current marketplace policy.")
        if policy["require_screening_answers"]:
            questions = state["job"].get("screening_questions", [])
            answers = draft.get("screening_answers", [])
            if len(answers) < len(questions) or any(
                not answer.strip() or answer.strip() == SCREENING_PLACEHOLDER
                for answer in answers[:len(questions)]
            ):
                reasons.append(MISSING_ANSWERS_REASON)

    verdict = ComplianceVerdict(passed=not reasons, reasons=reasons)
    return {"compliance_verdict": verdict.model_dump(mode="json")}
