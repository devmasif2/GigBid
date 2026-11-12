import re
from typing import Any

_CITATION_ID = re.compile(r"^\[(?P<id>[^\]]+)\]")


def sanitize_proposal(state: dict[str, Any]) -> dict[str, Any]:
    """Remove unsupported cited/factual lines before the draft reaches the Critic."""
    draft = state.get("proposal_draft")
    checks = state.get("claim_verification", [])
    if draft is None:
        raise ValueError("state must contain a proposal draft with a cover letter")
    if not isinstance(draft, dict):
        raise TypeError("proposal_draft must be an object")
    if not isinstance(draft.get("cover_letter"), str):
        raise TypeError("proposal_draft.cover_letter must be a string")
    if not isinstance(checks, list):
        raise TypeError("claim_verification must be a list")

    unsupported = {
        claim.get("claim")
        for claim in checks
        if isinstance(claim, dict) and claim.get("status") == "unsupported"
    }
    remaining_checks = [
        claim
        for claim in checks
        if isinstance(claim, dict) and claim.get("claim") not in unsupported
    ]
    kept_lines = [
        line
        for line in draft["cover_letter"].splitlines()
        if line.strip() not in unsupported
    ]
    cover_letter = "\n".join(kept_lines)
    remaining_ids = {
        match.group("id")
        for line in kept_lines
        if (match := _CITATION_ID.match(line.strip())) is not None
    }
    sanitized_draft = {
        **draft,
        "cover_letter": cover_letter,
        "evidence_ids": [
            evidence_id
            for evidence_id in draft.get("evidence_ids", [])
            if evidence_id in remaining_ids
        ],
    }
    return {
        "proposal_draft": sanitized_draft,
        "claim_verification_before_sanitization": checks,
        "claim_verification": remaining_checks,
    }
