import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from agent.marketplace_port import JobNotFoundError, MarketplaceUnavailableError


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float
    max: float
    currency: str


class SampleJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    title: str
    description: str
    required_skills: list[str] = Field(default_factory=list)
    budget: Budget
    duration_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    warning_signals: list[str] = Field(default_factory=list)
    connects_cost: int | None = None
    client_id: str | None = None
    posted_at_hour: int | None = None
    category: str | None = None
    data_kind: Literal["synthetic"] = "synthetic"


class JobLookupResult(BaseModel):
    job: SampleJob | None


class LocalSampleMarketplace:
    """Read-only adapter over the starter kit's illustrative sample jobs."""

    supports_remote_drafts = False

    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.environ.get(
            "GIGBID_JOBS_PATH", "data/sample/jobs.json"
        )
        self.path = path or Path(configured_path)

    def _jobs(self) -> list[SampleJob]:
        with self.path.open(encoding="utf-8") as file:
            data = json.load(file)
        return TypeAdapter(list[SampleJob]).validate_python(data)

    async def search_jobs(self, query: str) -> list[dict[str, object]]:
        jobs = self._jobs()
        terms = set(query.casefold().split())
        if not terms:
            return [job.model_dump(mode="json") for job in jobs]

        matches = []
        for job in jobs:
            text = " ".join(
                [job.title, job.description, *job.required_skills]
            ).casefold()
            if all(term in text for term in terms):
                matches.append(job.model_dump(mode="json"))
        return matches

    async def get_job(self, job_id: str) -> dict[str, object]:
        for job in self._jobs():
            if job.job_id == job_id:
                return job.model_dump(mode="json")
        raise JobNotFoundError(f"job not found: {job_id}")

    async def get_client_history(self, client_id: str) -> dict[str, object]:
        raise MarketplaceUnavailableError(
            "client history is not available in the local sample marketplace"
        )

    async def get_connects_balance(self) -> dict[str, object]:
        raise MarketplaceUnavailableError(
            "Connects balance is not available in the local sample marketplace"
        )

    async def list_proposals(self) -> list[dict[str, object]]:
        raise MarketplaceUnavailableError(
            "proposals are not available in the local sample marketplace"
        )

    async def create_proposal_draft(
        self, payload: dict[str, object], idempotency_key: str
    ) -> dict[str, object]:
        raise MarketplaceUnavailableError(
            "proposal writes are disabled in the local sample marketplace"
        )

    async def list_messages(self, proposal_id: str | None = None) -> list[dict[str, object]]:
        raise MarketplaceUnavailableError(
            "messages are not available in the local sample marketplace"
        )

    async def get_policy(self) -> dict[str, object]:
        raise MarketplaceUnavailableError(
            "marketplace policy is not available in the local sample marketplace"
        )
