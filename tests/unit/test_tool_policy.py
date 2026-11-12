from unittest.mock import AsyncMock

import pytest
from mcp.types import CallToolResult

from agent import marketplace_mcp_client, mcp_client, tool_policy
from agent.tool_policy import ToolAccessDenied, call_allowed_tool, require_tool_access


@pytest.mark.parametrize(
    ("caller", "server", "tool"),
    [
        ("fit_matcher", "portfolio", "get_case_study"),
        ("fit_matcher", "marketplace", "search_jobs"),
        ("job_inbox", "portfolio", "search_evidence"),
        ("job_inbox", "marketplace", "submit_proposal"),
        ("job_inbox", "marketplace", "create_proposal_draft"),
        ("fit_matcher", "marketplace", "create_proposal_draft"),
        ("proposal_publisher", "marketplace", "search_jobs"),
        ("proposal_publisher", "marketplace", "submit_proposal"),
        ("proposal_publisher", "workspace", "create_email_draft"),
        ("risk_assessor", "marketplace", "create_proposal_draft"),
        ("policy_reader", "marketplace", "get_client_history"),
        ("message_inbox", "marketplace", "create_proposal_draft"),
        ("message_inbox", "marketplace", "send_message"),
        ("pipeline_viewer", "marketplace", "create_proposal_draft"),
        ("pipeline_viewer", "marketplace", "send_message"),
        ("pipeline_viewer", "marketplace", "confirm_proposal"),
        ("portfolio_viewer", "portfolio", "get_case_study"),
        ("portfolio_viewer", "marketplace", "create_proposal_draft"),
        ("job_inbox", "workspace", "create_email_draft"),
        ("unknown", "portfolio", "search_evidence"),
        ("", "marketplace", "get_job"),
    ],
)
def test_policy_denies_unlisted_caller_server_or_tool(caller, server, tool):
    with pytest.raises(ToolAccessDenied):
        require_tool_access(caller, server, tool)


@pytest.mark.anyio
async def test_denied_tool_never_reaches_session():
    session = AsyncMock()
    with pytest.raises(ToolAccessDenied):
        await call_allowed_tool(
            session,
            caller="fit_matcher",
            server="workspace",
            tool="create_email_draft",
            arguments={"body": "do not send"},
        )
    session.call_tool.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("caller", "server", "tool"),
    [
        ("fit_matcher", "portfolio", "search_evidence"),
        ("portfolio_viewer", "portfolio", "search_evidence"),
        ("job_inbox", "marketplace", "search_jobs"),
        ("job_inbox", "marketplace", "get_job"),
        ("proposal_publisher", "marketplace", "create_proposal_draft"),
        ("risk_assessor", "marketplace", "get_client_history"),
        ("policy_reader", "marketplace", "get_marketplace_policy"),
        ("message_inbox", "marketplace", "list_messages"),
        ("pipeline_viewer", "marketplace", "list_proposals"),
        ("pipeline_viewer", "marketplace", "get_connects_balance"),
    ],
)
async def test_allowed_tool_is_forwarded(caller, server, tool):
    session = AsyncMock()
    response = CallToolResult(content=[])
    session.call_tool.return_value = response
    arguments = {"query": "example"}

    assert await call_allowed_tool(
        session, caller=caller, server=server, tool=tool, arguments=arguments
    ) is response
    session.call_tool.assert_awaited_once_with(tool, arguments)


@pytest.mark.anyio
async def test_marketplace_client_enforces_policy_before_starting_process(monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(marketplace_mcp_client, "stdio_client", start)
    monkeypatch.setattr(tool_policy, "_ALLOWED_TOOLS", {})

    with pytest.raises(ToolAccessDenied):
        await marketplace_mcp_client.get_job("job-1")
    start.assert_not_called()


@pytest.mark.anyio
async def test_fit_matcher_policy_is_enforced_before_starting_process(monkeypatch):
    start = AsyncMock()
    monkeypatch.setattr(mcp_client, "stdio_client", start)
    monkeypatch.setattr(tool_policy, "_ALLOWED_TOOLS", {})

    with pytest.raises(ToolAccessDenied):
        await mcp_client.retrieve_portfolio_evidence(["Python"])
    start.assert_not_called()
