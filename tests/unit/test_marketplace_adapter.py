import json

import pytest

from agent.marketplace_port import JobNotFoundError, MarketplaceUnavailableError
from mcp_servers.marketplace.local_sample import LocalSampleMarketplace


@pytest.fixture
def marketplace(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        json.dumps(
            [
                {
                    "job_id": "job-1",
                    "title": "Python data analysis",
                    "description": "Analyze tabular data and report findings.",
                    "required_skills": ["Python", "pandas"],
                    "budget": {"min": 100, "max": 200, "currency": "USD"},
                    "duration_days": 5,
                    "screening_questions": [],
                    "warning_signals": [],
                    "connects_cost": 4,
                },
                {
                    "job_id": "job-2",
                    "title": "React dashboard",
                    "description": "Build an interactive web interface.",
                    "required_skills": ["React", "TypeScript"],
                    "budget": {"min": 300, "max": 500, "currency": "USD"},
                    "duration_days": 10,
                    "screening_questions": [],
                    "warning_signals": [],
                    "connects_cost": 6,
                },
            ]
        ),
        encoding="utf-8",
    )
    return LocalSampleMarketplace(jobs_path)


@pytest.mark.anyio
async def test_search_filters_by_query_and_marks_data_as_synthetic(marketplace):
    jobs = await marketplace.search_jobs("python")

    assert [job["job_id"] for job in jobs] == ["job-1"]
    assert jobs[0]["data_kind"] == "synthetic"


@pytest.mark.anyio
async def test_empty_query_returns_all_local_sample_jobs(marketplace):
    jobs = await marketplace.search_jobs("")

    assert [job["job_id"] for job in jobs] == ["job-1", "job-2"]


@pytest.mark.anyio
async def test_get_job_returns_requested_job(marketplace):
    job = await marketplace.get_job("job-2")

    assert job["title"] == "React dashboard"


@pytest.mark.anyio
async def test_get_job_raises_for_unknown_id(marketplace):
    with pytest.raises(JobNotFoundError, match="job not found"):
        await marketplace.get_job("missing")


@pytest.mark.anyio
async def test_local_sample_marketplace_does_not_claim_to_support_writes(marketplace):
    with pytest.raises(MarketplaceUnavailableError, match="writes are disabled"):
        await marketplace.create_proposal_draft({}, "request-1")


@pytest.mark.anyio
async def test_default_adapter_can_read_starter_sample():
    marketplace = LocalSampleMarketplace()

    jobs = await marketplace.search_jobs("churn classification")

    assert [job["job_id"] for job in jobs] == ["sample-job-001"]
