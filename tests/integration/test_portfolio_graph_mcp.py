import json

import httpx
import pytest

from agent.mcp_client import PortfolioMCPError, retrieve_portfolio_evidence
from apps.api.main import app
from rag.ingest.portfolio import build_index, write_index


@pytest.mark.anyio
async def test_stdio_portfolio_client_preserves_sample_provenance():
    results = await retrieve_portfolio_evidence(["scikit-learn", "nonexistent-skill"])

    assert results[0][0].id == "evidence-001"
    assert results[0][0].data_kind == "synthetic"
    assert results[1] == []


@pytest.mark.anyio
async def test_stdio_portfolio_client_retrieves_ingested_chunks(tmp_path):
    (tmp_path / "example.md").write_text("Synthetic Python analytics example.")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "documents": [{
            "source_id": "example", "path": "example.md", "freelancer_id": "demo",
            "title": "Analytics", "type": "case_study", "skills": ["Python"],
            "data_kind": "synthetic", "client_industry": "retail",
        }],
    }))
    output = tmp_path / "portfolio.json"
    write_index(build_index(manifest, output_path=output), output)
    results = await retrieve_portfolio_evidence(["Python"], output)
    item = results[0][0]
    assert item.content == "Synthetic Python analytics example."
    assert item.freelancer_id == "demo"
    assert item.source == "local-manifest:example"
    assert item.data_kind == "synthetic"
    assert item.client_industry == "retail"


@pytest.mark.anyio
async def test_stdio_portfolio_client_retrieves_ingested_pdf(tmp_path, make_text_pdf):
    (tmp_path / "example.pdf").write_bytes(make_text_pdf("Synthetic Python engineer."))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "version": 1,
        "documents": [{
            "source_id": "pdf-example", "path": "example.pdf", "freelancer_id": "demo",
            "title": "Fictional CV", "type": "cv", "skills": ["Python"],
            "data_kind": "synthetic",
        }],
    }))
    output = tmp_path / "portfolio.json"
    write_index(build_index(manifest, output_path=output), output)
    results = await retrieve_portfolio_evidence(["Python"], output)
    item = results[0][0]
    assert item.content == "Synthetic Python engineer."
    assert item.source == "local-manifest:pdf-example"
    assert item.data_kind == "synthetic"


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
