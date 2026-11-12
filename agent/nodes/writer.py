"""Conservative template writer that quotes retrieved evidence and cites its IDs."""

import re
from typing import Any

from agent.handoffs import ProposalDraft

SCREENING_PLACEHOLDER = (
    "Draft this answer with the freelancer; the portfolio does not provide a verified answer."
)


def write_proposal(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    job_spec = state.get("job_spec")
    evidence = state.get("evidence", [])
    if job_spec is None:
        raise ValueError("state must contain a structured job_spec")
    if not isinstance(job_spec, dict):
        raise TypeError("job_spec must be an object")
    if not isinstance(evidence, list):
        raise TypeError("state.evidence must be a list")
    if not evidence:
        raise ValueError("cannot draft a proposal without portfolio evidence")

    citations: list[str] = []
    quoted_evidence: list[str] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise TypeError("each evidence item must be an object")
        evidence_id = item.get("id")
        content = item.get("content")
        if not isinstance(evidence_id, str) or not evidence_id.strip():
            raise ValueError("each evidence item must have an ID")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"evidence {evidence_id} has no content")
        citations.append(evidence_id)
        normalized_content = re.sub(r"\s+", " ", content).strip()
        quoted_evidence.append(f'[{evidence_id}] "{normalized_content}"')

    cover_letter = (
        f"I would be glad to discuss your project, {job_spec['title']}. "
        "Relevant portfolio evidence:\n"
        + "\n".join(quoted_evidence)
    )
    draft = ProposalDraft(
        job_id=job_spec["job_id"],
        cover_letter=cover_letter,
        screening_answers=[
            SCREENING_PLACEHOLDER
            for _ in job_spec.get("screening_questions", [])
        ],
        evidence_ids=citations,
    )
    return {"proposal_draft": draft.model_dump(mode="json")}
