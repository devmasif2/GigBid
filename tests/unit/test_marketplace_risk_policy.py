import pytest

from agent import marketplace_mcp_client
from agent.nodes.risk_assessor import assess_risk


def test_client_history_contributes_explicit_heuristic_flags():
    result = assess_risk({
        "job": {"title": "Task", "description": "Work"},
        "client_history": {
            "payment_verified": False,
            "jobs_posted": 10,
            "hire_rate": 0.1,
            "average_rating": 3.0,
        },
    })["risk_report"]
    assert result["score"] == 0.5
    assert set(result["flags"]) == {"unverified_payment", "low_hire_rate", "low_client_rating"}


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("Only apply if you can guarantee 100% accuracy.", True),
        ("We require a guaranteed first-page ranking.", True),
        ("We cannot guarantee results; describe limitations.", False),
        ("The manufacturer provides a product guarantee.", False),
    ],
)
def test_guaranteed_results_pattern_flags_specific_unrealistic_demands(text, flagged):
    report = assess_risk({"job": {"title": "Project", "description": text}})["risk_report"]
    assert ("guaranteed_results" in report["flags"]) is flagged


@pytest.mark.anyio
async def test_client_history_rejects_wrong_client_and_invalid_policy(monkeypatch):
    async def fake_call(_caller, tool, _arguments):
        if tool == "get_client_history":
            return {
                "client_id": "other", "payment_verified": True, "jobs_posted": 1,
                "hire_rate": 1.0, "average_rating": None,
            }
        return {"version": 1}

    monkeypatch.setattr(marketplace_mcp_client, "_call_tool", fake_call)
    with pytest.raises(marketplace_mcp_client.MarketplaceMCPError, match="mismatched"):
        await marketplace_mcp_client.get_client_history("expected")
    with pytest.raises(marketplace_mcp_client.MarketplaceMCPError, match="invalid data"):
        await marketplace_mcp_client.get_marketplace_policy()
