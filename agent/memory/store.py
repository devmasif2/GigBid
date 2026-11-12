"""Explicit, conservative promotion rules for graph memory."""

import re
from typing import Any

_SPACE = re.compile(r"\s+")


def trace_event(
    trace: list[dict[str, Any]] | None,
    *,
    node: str,
    status: str,
    observation: str,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """Append an audit-friendly event; raw tool payloads are intentionally excluded."""
    event = {
        "node": node,
        "status": status,
        "observation": observation,
    }
    if trace_id:
        event["trace_id"] = trace_id
    return [*(trace or []), event]


def _normalize(text: str) -> str:
    return _SPACE.sub(" ", text.casefold()).strip()


def promote_style_memory(
    style_memory: list[dict[str, Any]] | None,
    *,
    edited_text: str,
    prior_text: str,
    edit_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Promote only repeated, user-confirmed edit patterns, never a raw draft."""
    if edit_count < 3 or _normalize(edited_text) == _normalize(prior_text):
        return list(style_memory or []), None
    event = {
        "kind": "style_preference",
        "rule": "User prefers the revised wording over the prior draft.",
        "source": "repeated_user_edit",
        "evidence_count": edit_count,
    }
    existing = [item for item in (style_memory or []) if item.get("rule") != event["rule"]]
    return [*existing, event], event


def promote_outcome_memory(
    outcome_memory: list[dict[str, Any]] | None,
    *,
    job_category: str,
    outcome: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Store only a normalized marketplace outcome, not raw client/tool content."""
    if outcome not in {"replied", "hired", "lost"}:
        return list(outcome_memory or []), None
    event = {"kind": "outcome", "job_category": job_category, "outcome": outcome}
    return [*(outcome_memory or []), event], event
