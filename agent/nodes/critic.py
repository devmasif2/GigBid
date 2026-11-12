"""Deterministic proposal structure and citation critic."""

from typing import Any

from agent.handoffs import Critique


def critique_proposal(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    draft = state.get("proposal_draft")
    evidence = state.get("evidence", [])
    if draft is None or evidence is None:
        raise ValueError("state must contain proposal_draft and evidence")
    if not isinstance(draft, dict) or not isinstance(evidence, list):
        raise TypeError("proposal_draft must be an object and evidence must be a list")

    evidence_ids = {
        item.get("id") for item in evidence if isinstance(item, dict) and item.get("id")
    }
    draft_ids = set(draft.get("evidence_ids", []))
    reasons: list[str] = []
    if not draft.get("cover_letter", "").strip():
        reasons.append("Proposal is empty.")
    if not draft_ids:
        reasons.append("Proposal has no evidence citations.")
    elif not draft_ids.issubset(evidence_ids):
        reasons.append("Proposal cites evidence that was not retrieved.")

    critique = Critique(
        passed=not reasons,
        reasons=reasons,
        revision_count=state.get("revision_count", 0),
    )
    return {"critique": critique.model_dump(mode="json")}
