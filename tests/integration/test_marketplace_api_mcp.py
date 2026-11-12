from pathlib import Path

import httpx
import pytest

from agent import marketplace_mcp_client
from agent.marketplace_mcp_client import MarketplaceMCPError, MarketplaceMCPTransportError
from apps.api.main import app


@pytest.mark.anyio
async def test_marketplace_unavailable_then_recovers(tmp_path, monkeypatch):
    sample_path = tmp_path / "jobs.json"
    monkeypatch.setenv("GIGBID_JOBS_PATH", str(sample_path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        unavailable_list = await client.get("/jobs")
        unavailable_detail = await client.get("/jobs/sample-job-001")
        sample_path.write_text(Path("data/sample/jobs.json").read_text(encoding="utf-8"))
        recovered = await client.get("/jobs")
        found = await client.get("/jobs/sample-job-001")
        missing = await client.get("/jobs/not-a-job")

    assert unavailable_list.status_code == 503
    assert unavailable_detail.status_code == 503
    assert recovered.status_code == 200
    assert len(recovered.json()) == 2
    assert found.status_code == 200
    assert found.json()["data_kind"] == "synthetic"
    assert missing.status_code == 404


@pytest.mark.anyio
async def test_malformed_marketplace_data_is_not_treated_as_not_found(tmp_path, monkeypatch):
    path = tmp_path / "jobs.json"
    path.write_text("invalid json", encoding="utf-8")
    monkeypatch.setenv("GIGBID_JOBS_PATH", str(path))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/jobs/unknown-job")
    assert response.status_code == 503


@pytest.mark.anyio
async def test_marketplace_transport_retries_without_retrying_tool_errors(monkeypatch):
    attempts = 0

    async def flaky(_tool, _argument):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise MarketplaceMCPTransportError("connection closed")
        return []

    monkeypatch.setattr(marketplace_mcp_client, "_call_once", flaky)
    assert await marketplace_mcp_client.search_jobs("Python") == []
    assert attempts == 3

    attempts = 0

    async def invalid(_tool, _argument):
        nonlocal attempts
        attempts += 1
        raise MarketplaceMCPError("invalid result")

    monkeypatch.setattr(marketplace_mcp_client, "_call_once", invalid)
    with pytest.raises(MarketplaceMCPError, match="invalid result"):
        await marketplace_mcp_client.get_job("job-1")
    assert attempts == 1


@pytest.mark.anyio
async def test_draft_client_is_idempotent_across_real_server_processes(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGBID_MARKETPLACE_DB", str(tmp_path / "drafts.sqlite3"))
    monkeypatch.setenv("GIGBID_JOBS_PATH", "data/sample/jobs.json")
    request = {
        "job_id": "sample-job-001",
        "cover_letter": "Draft for local review.",
        "price": 350,
        "idempotency_key": "client-idempotency-key",
        "trace_id": "trace-from-client",
    }

    preview = await marketplace_mcp_client.create_proposal_draft(**request)
    first = await marketplace_mcp_client.create_proposal_draft(**request, dry_run=False)
    second = await marketplace_mcp_client.create_proposal_draft(**request, dry_run=False)

    assert (preview.outcome, first.outcome, second.outcome) == (
        "preview",
        "created",
        "already_exists",
    )
    assert first.draft.created_at == second.draft.created_at
    assert first.connects_cost_if_submitted == 8
    with pytest.raises(MarketplaceMCPError, match="failed or is unavailable"):
        await marketplace_mcp_client.create_proposal_draft(
            **{**request, "price": 999}, dry_run=False
        )
