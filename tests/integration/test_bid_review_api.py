import json
import sqlite3
from contextlib import closing

import httpx
import pytest

from apps.api.main import app

SAMPLE_JOBS = "data/sample/jobs.json"


@pytest.fixture
def environment(tmp_path, monkeypatch):
    evidence_path = tmp_path / "verified-test-evidence.json"
    evidence_path.write_text(
        json.dumps(
            [{
                "id": "case-python",
                "title": "Python analytics",
                "type": "case_study",
                "source": "test fixture",
                "skills": ["Python"],
                "content": "Built a Python classification baseline.",
                "data_kind": "real",
            }]
        ),
        encoding="utf-8",
    )
    database = tmp_path / "marketplace.sqlite3"
    monkeypatch.setenv("GIGBID_PORTFOLIO_PATH", str(evidence_path))
    monkeypatch.setenv("GIGBID_MARKETPLACE_DB", str(database))
    monkeypatch.setenv("GIGBID_JOBS_PATH", SAMPLE_JOBS)
    return database


def _start_request(thread_id):
    return {
        "thread_id": thread_id,
        "input": {
            "job": {
                "job_id": "sample-job-001",
                "title": "Python classifier",
                "description": "Build a classifier.",
                "required_skills": ["Python"],
                "budget": {"min": 250, "max": 450, "currency": "USD"},
                "warning_signals": [],
                "connects_cost": 8,
            }
        },
    }


def _count(database, table):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.mark.anyio
async def test_bid_review_restores_edits_and_creates_one_draft_after_approval(environment):
    thread = "bid-api-review-integration"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        start = await client.post("/graphs/bid/start", json=_start_request(thread))
        assert start.status_code == 200
        assert start.json()["status"] == "interrupted"
        restored = await client.get(f"/graphs/bid/{thread}")
        assert restored.json()["interrupts"] == start.json()["interrupts"]
        edited = await client.post(
            f"/graphs/bid/{thread}/approval",
            json={
                "action": "edit",
                "cover_letter": (
                    "I have ten years of experience.\n"
                    '[case-python] "Built a Python classification baseline."'
                ),
            },
        )
        assert edited.status_code == 200
        review = edited.json()["interrupts"][0]
        assert review["edit_validation"]["passed"] is True
        assert "ten years" not in review["proposal_draft"]["cover_letter"]
        assert review["dry_run"]["external_action_taken"] is False
        assert not environment.exists()  # nothing touched the marketplace before approval

        approved = await client.post(f"/graphs/bid/{thread}/approval", json={"action": "approve"})
        repeated = await client.post(f"/graphs/bid/{thread}/approval", json={"action": "approve"})

    state = approved.json()["state"]
    assert state["approval_status"] == "approved"
    assert state["draft_publication"]["outcome"] == "created"
    assert state["draft_publication"]["draft"]["status"] == "draft"
    assert state["draft_publication"]["external_action_taken"] is False
    assert "ten years" not in state["draft_publication"]["draft"]["cover_letter"]
    assert repeated.status_code == 409
    assert _count(environment, "proposal_drafts") == 1
    assert _count(environment, "audit_log") == 1


@pytest.mark.anyio
async def test_api_validates_and_rechecks_screening_answers(environment):
    thread = "bid-api-screening"
    request = _start_request(thread)
    request["input"]["job"]["screening_questions"] = ["Describe relevant work."]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        start = await client.post("/graphs/bid/start", json=request)
        letter = start.json()["interrupts"][0]["proposal_draft"]["cover_letter"]
        url = f"/graphs/bid/{thread}/approval"
        invalid = await client.post(url, json={
            "action": "edit", "cover_letter": letter, "screening_answers": [],
        })
        assert invalid.status_code == 422
        edited = await client.post(url, json={
            "action": "edit", "cover_letter": letter,
            "screening_answers": ['[case-python] "Built a Python classification baseline."'],
        })
        assert edited.status_code == 200
        assert edited.json()["interrupts"][0]["edit_validation"]["passed"] is True
        restored = await client.get(f"/graphs/bid/{thread}")
        assert restored.json()["interrupts"][0]["proposal_draft"]["screening_answers"] == [
            '[case-python] "Built a Python classification baseline."'
        ]
        assert not environment.exists()


@pytest.mark.anyio
async def test_marketplace_outage_after_approval_recovers_without_duplicate_draft(
    environment, monkeypatch
):
    thread = "bid-api-outage"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        start = await client.post("/graphs/bid/start", json=_start_request(thread))
        assert start.json()["status"] == "interrupted"

        monkeypatch.setenv("GIGBID_JOBS_PATH", str(environment.parent / "missing-jobs.json"))
        failed = await client.post(f"/graphs/bid/{thread}/approval", json={"action": "approve"})
        premature_approval = await client.post(
            f"/graphs/bid/{thread}/approval", json={"action": "approve"}
        )
        pending = await client.get(f"/graphs/bid/{thread}")

        monkeypatch.setenv("GIGBID_JOBS_PATH", SAMPLE_JOBS)
        recovered = await client.post(f"/graphs/bid/{thread}/continue")
        again = await client.post(f"/graphs/bid/{thread}/continue")

    assert failed.status_code == 503
    assert premature_approval.status_code == 409
    assert pending.json()["status"] == "running"
    assert recovered.status_code == 200
    assert recovered.json()["state"]["draft_publication"]["outcome"] == "created"
    assert again.status_code == 409
    assert _count(environment, "proposal_drafts") == 1
