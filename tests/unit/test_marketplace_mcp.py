import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolAnnotations

from mcp_servers.marketplace import server
from mcp_servers.marketplace.local_sample import LocalSampleMarketplace


@pytest.mark.anyio
async def test_marketplace_mcp_exposes_read_only_job_tools(tmp_path, monkeypatch):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(
        '[{"job_id":"job-1","title":"Python task","description":"Write Python",'
        '"required_skills":["Python"],"budget":{"min":100,"max":200,"currency":"USD"},'
        '"duration_days":3,"screening_questions":[],"warning_signals":[],"connects_cost":2}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "marketplace", LocalSampleMarketplace(jobs_path))

    async with create_connected_server_and_client_session(server.mcp) as client:
        tools = await client.list_tools()
        result = await client.call_tool("search_jobs", {"query": "python"})
        found_job = await client.call_tool("get_job", {"job_id": "job-1"})
        missing_job = await client.call_tool("get_job", {"job_id": "missing"})
        invalid_job = await client.call_tool("get_job", {"job_id": ""})
        invalid_search = await client.call_tool("search_jobs", {"query": "x" * 501})
        sample_mode_calls = [
            await client.call_tool("get_client_history", {"client_id": "client-1"}),
            await client.call_tool("get_connects_balance"),
            await client.call_tool("list_proposals"),
            await client.call_tool("list_messages"),
            await client.call_tool("get_marketplace_policy"),
        ]

    tool_by_name = {tool.name: tool for tool in tools.tools}
    read_tools = {
        "search_jobs",
        "get_job",
        "get_client_history",
        "get_connects_balance",
        "list_proposals",
        "list_messages",
        "get_marketplace_policy",
    }
    assert set(tool_by_name) == read_tools | {"create_proposal_draft"}
    assert all(tool_by_name[name].annotations.readOnlyHint for name in read_tools)
    assert all(call.isError for call in sample_mode_calls)
    assert tool_by_name["search_jobs"].annotations == ToolAnnotations(readOnlyHint=True)
    assert tool_by_name["get_job"].annotations == ToolAnnotations(readOnlyHint=True)
    assert tool_by_name["get_job"].inputSchema["properties"]["job_id"]["minLength"] == 1
    assert tool_by_name["get_job"].inputSchema["properties"]["job_id"]["maxLength"] == 200
    assert tool_by_name["search_jobs"].inputSchema["properties"]["query"]["maxLength"] == 500
    assert result.isError is False
    assert result.structuredContent["result"][0]["job_id"] == "job-1"
    assert found_job.structuredContent["job"]["job_id"] == "job-1"
    assert missing_job.isError is False
    assert missing_job.structuredContent["job"] is None
    assert invalid_job.isError is True
    assert invalid_search.isError is True
