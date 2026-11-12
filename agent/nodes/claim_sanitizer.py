import re
from typing import Any

_CITATION_ID = re.compile(r"^\[(?P<id>[^\]]+)\]")


def _source_lines(claim: dict[str, Any], line_count: int) -> list[int]:
    positions = claim.get("source_lines", [])
    if not isinstance(positions, list) or any(
        not isinstance(position, int)
        or isinstance(position, bool)
        or not 0 <= position < line_count
        for position in positions
    ):
        raise ValueError("invalid claim source line")
    return positions


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

    unsupported_checks = [
        claim for claim in checks
        if isinstance(claim, dict) and claim.get("status") == "unsupported"
    ]
    lines = draft["cover_letter"].splitlines()
    removed_lines = set()
    for claim in unsupported_checks:
        positions = _source_lines(claim, len(lines))
        if positions:
            removed_lines.update(positions)
        else:
            text = claim.get("claim")
            if text == draft["cover_letter"].strip():
                removed_lines.update(range(len(lines)))
            else:
                matched = {index for index, line in enumerate(lines) if line.strip() == text}
                if not matched:
                    raise ValueError("unsupported claim cannot be located in the draft")
                removed_lines.update(matched)
    kept_lines = [line for index, line in enumerate(lines) if index not in removed_lines]
    new_positions = {
        old: new for new, old in enumerate(index for index in range(len(lines)) if index not in removed_lines)
    }
    remaining_checks = []
    for claim in checks:
        if not isinstance(claim, dict) or claim.get("status") == "unsupported":
            continue
        positions = _source_lines(claim, len(lines))
        if positions:
            if any(position in removed_lines for position in positions):
                continue
            claim = {**claim, "source_lines": [new_positions[position] for position in positions]}
        elif removed_lines:
            continue
        remaining_checks.append(claim)
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
