import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.portfolio import server
from mcp_servers.portfolio.service import Portfolio


@pytest.mark.anyio
async def test_portfolio_mcp_exposes_read_tools_and_returns_evidence(tmp_path, monkeypatch):
    evidence_path = tmp_path / "portfolio.json"
    evidence_path.write_text(
        json.dumps(
            [
                {
                    "id": "case-1",
                    "title": "Python data pipeline",
                    "type": "case_study",
                    "source": "case-studies/pipeline.md",
                    "date": "2026-01-15",
                    "outcome": None,
                    "project": "Northstar",
                    "skills": ["Python"],
                    "content": "Built an automated data pipeline.",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "portfolio", Portfolio(evidence_path))

    async with create_connected_server_and_client_session(server.mcp) as client:
        tools = await client.list_tools()
        resources = await client.list_resource_templates()
        prompts = await client.list_prompts()
        result = await client.call_tool(
            "search_evidence", {"requirement": "Python data pipeline", "k": 3}
        )
        case_study = await client.call_tool("get_case_study", {"case_id": "case-1"})
        skills = await client.call_tool("list_skills")

    tool_names = {tool.name for tool in tools.tools}
    assert {"search_evidence", "get_case_study", "list_skills"} <= tool_names
    assert all(tool.annotations.readOnlyHint for tool in tools.tools)
    assert result.isError is False
    assert result.structuredContent["result"][0]["id"] == "case-1"
    assert case_study.structuredContent["source"] == "case-studies/pipeline.md"
    assert skills.structuredContent["result"] == ["Python"]
    resource_templates = resources.model_dump(mode="json", by_alias=True)["resourceTemplates"]
    assert {template["uriTemplate"] for template in resource_templates} == {
        "portfolio://case/{case_id}",
        "portfolio://proposal/{proposal_id}",
    }
    assert {prompt.name for prompt in prompts.prompts} == {"answer_screening_question"}
