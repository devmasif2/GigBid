"""Deterministic skill coverage over portfolio items returned by the Portfolio service."""

from typing import Any

from agent.handoffs import FitReport
from agent.mcp_client import retrieve_portfolio_evidence
from mcp_servers.portfolio.service import EvidenceItem, Portfolio


def match_fit(
    state: dict[str, Any], portfolio: Portfolio | None = None
) -> dict[str, dict[str, Any]]:
    required_skills = _required_skills(state)
    evidence_store = portfolio or Portfolio()
    results = [evidence_store.search_evidence(skill, k=5) for skill in required_skills]
    return _fit_report(required_skills, results)


def _required_skills(state: dict[str, Any]) -> list[str]:
    job_spec = state.get("job_spec")
    if job_spec is None:
        raise ValueError("state must contain a structured job_spec")
    if not isinstance(job_spec, dict):
        raise TypeError("job_spec must be an object")
    required_skills = job_spec.get("required_skills", [])
    if not isinstance(required_skills, list):
        raise TypeError("job_spec.required_skills must be a list")
    if not all(isinstance(skill, str) for skill in required_skills):
        raise TypeError("job_spec.required_skills must contain strings")
    if not all(skill.strip() for skill in required_skills):
        raise ValueError("job_spec.required_skills must contain non-empty strings")

    return required_skills


async def match_fit_mcp(
    state: dict[str, Any], portfolio: Portfolio | None = None
) -> dict[str, Any]:
    required_skills = _required_skills(state)
    results = await retrieve_portfolio_evidence(
        required_skills, portfolio.path if portfolio is not None else None
    )
    return _fit_report(required_skills, results)


def _fit_report(
    required_skills: list[str], results: list[list[EvidenceItem]]
) -> dict[str, Any]:
    matched: list[str] = []
    missing: list[str] = []
    evidence_ids: set[str] = set()
    retrieved_items: dict[str, Any] = {}

    for requirement, evidence in zip(required_skills, results, strict=True):
        retrieved_items.update({item.id: item for item in evidence})
        evidence_skills = {
            skill.casefold()
            for item in evidence
            for skill in item.skills
        }
        if requirement.casefold() in evidence_skills:
            matched.append(requirement)
            evidence_ids.update(item.id for item in evidence)
        else:
            missing.append(requirement)

    score = len(matched) / len(required_skills) if required_skills else 0.0
    report = FitReport(
        score=score,
        matched_skills=matched,
        missing_skills=missing,
        evidence_ids=sorted(evidence_ids),
    )
    return {
        "fit_report": report.model_dump(mode="json"),
        "evidence": [
            item.model_dump(mode="json")
            for item_id, item in retrieved_items.items()
            if item_id in evidence_ids
        ],
    }
