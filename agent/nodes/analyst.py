"""Deterministic baseline extraction of structured fields already present in a job post."""

from typing import Any

from agent.handoffs import JobSpec


def analyze_job(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    job = state.get("job")
    if job is None:
        raise ValueError("state must contain a job object")
    if not isinstance(job, dict):
        raise TypeError("job must be an object")

    job_id = job.get("job_id")
    title = job.get("title")
    if not isinstance(job_id, str):
        raise TypeError("job.job_id must be a string")
    if not job_id.strip():
        raise ValueError("job.job_id must be a non-empty string")
    if not isinstance(title, str):
        raise TypeError("job.title must be a string")
    if not title.strip():
        raise ValueError("job.title must be a non-empty string")

    budget = job.get("budget") or {}
    if not isinstance(budget, dict):
        raise TypeError("job.budget must be an object")

    description = job.get("description", "")
    if not isinstance(description, str):
        raise TypeError("job.description must be a string")
    deliverables = [
        sentence.strip()
        for sentence in description.replace("\n", " ").split(".")
        if sentence.strip()
    ]

    spec = JobSpec(
        job_id=job_id,
        title=title,
        deliverables=deliverables,
        required_skills=job.get("required_skills", []),
        budget_min=budget.get("min"),
        budget_max=budget.get("max"),
        budget_currency=budget.get("currency"),
        duration_days=job.get("duration_days"),
        screening_questions=job.get("screening_questions", []),
        connects_cost=job.get("connects_cost"),
    )
    return {"job_spec": spec.model_dump(mode="json")}
