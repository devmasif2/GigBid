"""Fail-closed tool permissions for the currently integrated MCP callers."""

import logging
from types import MappingProxyType
from typing import Any, Protocol

from mcp.types import CallToolResult

_LOGGER = logging.getLogger(__name__)

_ALLOWED_TOOLS = MappingProxyType(
    {
        "fit_matcher": frozenset({("portfolio", "search_evidence")}),
        "github_ingest": frozenset({("github", "get_file_contents")}),
        "job_inbox": frozenset({("marketplace", "search_jobs"), ("marketplace", "get_job")}),
        "risk_assessor": frozenset({("marketplace", "get_client_history")}),
        "policy_reader": frozenset({("marketplace", "get_marketplace_policy")}),
        "message_inbox": frozenset({("marketplace", "list_messages")}),
        "pipeline_viewer": frozenset({
            ("marketplace", "list_proposals"), ("marketplace", "get_connects_balance")
        }),
        "proposal_publisher": frozenset({("marketplace", "create_proposal_draft")}),
    }
)


class ToolAccessDenied(PermissionError):
    """A caller attempted to use an MCP tool outside its policy."""


class ToolSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> CallToolResult: ...


def require_tool_access(caller: str, server: str, tool: str) -> None:
    if (server, tool) not in _ALLOWED_TOOLS.get(caller, frozenset()):
        _LOGGER.warning("Denied MCP tool access for caller=%s server=%s tool=%s", caller, server, tool)
        raise ToolAccessDenied(f"MCP tool access denied for {caller}: {server}/{tool}")


async def call_allowed_tool(
    session: ToolSession,
    *,
    caller: str,
    server: str,
    tool: str,
    arguments: dict[str, Any],
) -> CallToolResult:
    require_tool_access(caller, server, tool)
    return await session.call_tool(tool, arguments)
