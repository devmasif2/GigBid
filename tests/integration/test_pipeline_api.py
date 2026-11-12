import httpx
import pytest

from agent import marketplace_mcp_client
from agent.marketplace_mcp_client import MarketplaceMCPError
from apps.api.main import app


@pytest.mark.anyio
async def test_pipeline_sample_mode_is_explicitly_unavailable(monkeypatch):
    monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "sample")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/pipeline")
    assert response.status_code == 503
    assert response.json()["detail"] == "Simulator pipeline is unavailable."


@pytest.mark.anyio
async def test_pipeline_rejects_malformed_marketplace_responses(monkeypatch):
    async def invalid_proposals(_caller, _tool, _args):
        return {"result": [{"proposal_id": "missing-fields"}]}

    monkeypatch.setattr(marketplace_mcp_client, "_call_tool", invalid_proposals)
    with pytest.raises(MarketplaceMCPError, match="invalid proposals"):
        await marketplace_mcp_client.list_proposals()

    async def invalid_balance(_caller, _tool, _args):
        return {"balance": -1}

    monkeypatch.setattr(marketplace_mcp_client, "_call_tool", invalid_balance)
    with pytest.raises(MarketplaceMCPError, match="invalid data"):
        await marketplace_mcp_client.get_connects_balance()


@pytest.mark.anyio
async def test_pipeline_fails_closed_when_balance_is_unavailable(monkeypatch):
    async def read(_caller, tool, _args):
        if tool == "list_proposals":
            return {"result": []}
        raise MarketplaceMCPError("unavailable")

    monkeypatch.setattr(marketplace_mcp_client, "_call_tool", read)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/pipeline")
    assert response.status_code == 503
    assert "proposals" not in response.json()
