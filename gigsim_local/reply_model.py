"""Deterministic client-decision model for the local GigSim stand-in.

This replaces the original design's LLM client with an explicit, inspectable function so reply and
hire rates are reproducible. It is a stand-in, not a claim about real client behaviour.

score = 0.05
      + 0.45 * share of the client's must-have skills mentioned in the proposal
      + 0.20 * share of job-title keywords mentioned
      + 0.10 if the text contains at least two numbers (concrete detail)
      + 0.05 if every screening question has an answer
      + price term: +0.15 if price <= the client's ceiling, -0.25 if price > 1.3 * ceiling
      - 0.30 if the client dislikes generic openings and the text uses one
      - 0.15 if the text is under 150 characters
      - 0.50 if the text asks to go off-platform or guarantees results
The score is clamped to [0, 1], then a deterministic per-proposal noise in [-0.08, 0.08) is added.
Outcome: ignored < threshold <= replied < threshold + 0.15 <= interview < threshold + 0.28 <= hired.
"""

import hashlib
import re
from dataclasses import dataclass

GENERIC_OPENERS = (
    "i am writing to apply",
    "dear sir",
    "dear hiring manager",
    "i am excited to apply",
    "i believe i am the perfect",
    "i am a hardworking",
)
VIOLATION_PATTERNS = (
    re.compile(r"\b(whatsapp|telegram|skype|signal)\b", re.IGNORECASE),
    re.compile(r"\bpay(ment)?\b.{0,20}\boutside\b", re.IGNORECASE),
    re.compile(r"\bguarantee[sd]?\b", re.IGNORECASE),
)
STOPWORDS = {"build", "with", "using", "for", "and", "the", "add", "from", "into", "that", "your"}


@dataclass(frozen=True)
class Decision:
    score: float
    noisy_score: float
    outcome: str  # ignored | replied | interview | hired
    violations: bool


def unit_interval(seed: int, key: str) -> float:
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _mentions(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def title_keywords(title: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z+#.-]{3,}", title)
    return [word for word in words if word.casefold() not in STOPWORDS]


def has_violation(text: str) -> bool:
    return any(pattern.search(text) for pattern in VIOLATION_PATTERNS)


def decide(
    *,
    seed: int,
    proposal_id: str,
    cover_letter: str,
    price: float,
    answers: int,
    questions: int,
    job_title: str,
    hidden: dict,
) -> Decision:
    must_have = hidden["must_have_skills"]
    coverage = (
        sum(_mentions(cover_letter, skill) for skill in must_have) / len(must_have)
        if must_have
        else 0.0
    )
    keywords = title_keywords(job_title)
    overlap = (
        sum(_mentions(cover_letter, word) for word in keywords) / len(keywords)
        if keywords
        else 0.0
    )
    score = 0.05 + 0.45 * coverage + 0.20 * overlap
    if len(re.findall(r"\d+", cover_letter)) >= 2:
        score += 0.10
    if questions == 0 or answers >= questions:
        score += 0.05
    ceiling = hidden["budget_ceiling"]
    if price <= ceiling:
        score += 0.15
    elif price > 1.3 * ceiling:
        score -= 0.25
    lowered = cover_letter.casefold()
    if hidden["dislikes_generic"] and any(opener in lowered for opener in GENERIC_OPENERS):
        score -= 0.30
    if len(cover_letter) < 150:
        score -= 0.15
    violations = has_violation(cover_letter)
    if violations:
        score -= 0.50
    score = min(1.0, max(0.0, score))

    noisy = score + (unit_interval(seed, f"{proposal_id}:noise") - 0.5) * 0.16
    threshold = hidden["reply_threshold"]
    if noisy >= threshold + 0.28:
        outcome = "hired"
    elif noisy >= threshold + 0.15:
        outcome = "interview"
    elif noisy >= threshold:
        outcome = "replied"
    else:
        outcome = "ignored"
    return Decision(round(score, 4), round(noisy, 4), outcome, violations)
