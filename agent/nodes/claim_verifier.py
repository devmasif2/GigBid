from typing import Any

from rag.verify import verify_claims


def verify_proposal(state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    draft = state.get("proposal_draft")
    evidence = state.get("evidence", [])
    if draft is None:
        raise ValueError("state must contain a proposal draft")
    if not isinstance(draft, dict):
        raise TypeError("proposal_draft must be an object")
    if not isinstance(draft.get("cover_letter"), str):
        raise TypeError("proposal_draft.cover_letter must be a string")
    return {
        "claim_verification": verify_claims(draft["cover_letter"], evidence)
    }
