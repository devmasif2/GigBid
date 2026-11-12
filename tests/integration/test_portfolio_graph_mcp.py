import httpx
import pytest

from agent.mcp_client import PortfolioMCPError, retrieve_portfolio_evidence
from apps.api.main import app


@pytest.mark.anyio
async def test_stdio_portfolio_client_preserves_sample_provenance():
    results = await retrieve_portfolio_evidence(["scikit-learn", "nonexistent-skill"])

    assert results[0][0].id == "evidence-001"
    assert results[0][0].data_kind == "synthetic"
    assert results[1] == []


@pytest.mark.anyio
async def test_stdio_portfolio_client_fails_explicitly_for_missing_data(tmp_path):
    with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
        await retrieve_portfolio_evidence(["Python"], tmp_path / "missing.json")


@pytest.mark.anyio
async def test_bid_api_surfaces_portfolio_mcp_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGBID_PORTFOLIO_PATH", str(tmp_path / "missing.json"))
    request = {
        "thread_id": "unavailable-portfolio",
        "input": {
            "job": {
                "job_id": "job-1",
                "title": "Python task",
                "description": "Use Python.",
                "required_skills": ["Python"],
            }
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/graphs/bid/start", json=request)
        request["thread_id"] = "unavailable-portfolio-stream"
        stream = await client.post("/graphs/bid/stream", json=request)

    assert response.status_code == 503
    assert "Portfolio MCP" in response.json()["detail"]
    assert "event: error" in stream.text
    assert "Portfolio MCP" in stream.text
    assert "event: complete" not in stream.text
