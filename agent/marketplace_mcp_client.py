"""Client for the local Marketplace MCP server."""

import logging
import os
import sys
from typing import Any, Literal

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from agent.mcp_client import _TIMEOUT_SECONDS, retry_transport
from agent.tool_policy import call_allowed_tool, require_tool_access
from mcp_servers.marketplace.drafts import ProposalDraftResult
from mcp_servers.marketplace.local_sample import JobLookupResult, SampleJob

_LOGGER = logging.getLogger(__name__)


class MarketplaceMCPError(RuntimeError):
    """The Marketplace MCP server could not provide valid data."""


class MarketplaceMCPTransportError(MarketplaceMCPError):
    """The local server connection failed or timed out."""


class ClientHistory(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    client_id: str
    payment_verified: bool
    jobs_posted: int = Field(ge=0)
    hire_rate: float = Field(ge=0, le=1)
    average_rating: float | None = Field(ge=0, le=5)


class MarketplacePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(ge=1)
    connects_multiplier: float = Field(gt=0, allow_inf_nan=False)
    max_cover_letter_chars: int = Field(gt=0)
    require_screening_answers: bool
    banned_phrases: list[str]
    rules: list[str]


class MarketplaceMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    message_id: str = Field(min_length=1, max_length=200)
    proposal_id: str = Field(min_length=1, max_length=200)
    job_id: str = Field(min_length=1, max_length=200)
    sender: Literal["client", "freelancer"]
    body: str = Field(min_length=1, max_length=5000)
    sent_at_hour: int = Field(ge=0)


class ConnectsBalance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    balance: int = Field(ge=0)


class PipelineProposal(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    proposal_id: str = Field(min_length=1, max_length=200)
    job_id: str = Field(min_length=1, max_length=200)
    status: Literal["draft", "submitted", "viewed", "replied", "interview", "hired", "lost"]
    price: float = Field(gt=0, allow_inf_nan=False)
    connects_spent: int = Field(ge=0)
    created_at_hour: int = Field(ge=0)
    updated_at_hour: int = Field(ge=0)


async def _call_tool(caller: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    require_tool_access(caller, "marketplace", tool)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.marketplace.server"],
        env=os.environ.copy(),
    )
    try:
        with anyio.fail_after(_TIMEOUT_SECONDS):
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                try:
                    await session.initialize()
                    response = await call_allowed_tool(
                        session,
                        caller=caller,
                        server="marketplace",
                        tool=tool,
                        arguments=arguments,
                    )
                    if response.isError:
                        detail = " ".join(
                            getattr(block, "text", "") for block in response.content
                        )
                        _LOGGER.warning("Marketplace MCP %s failed: %.200s", tool, detail)
                        raise MarketplaceMCPError(f"Marketplace MCP {tool} failed")
                    content = response.structuredContent
                    if not isinstance(content, dict):
                        raise MarketplaceMCPError("Marketplace MCP returned invalid data")
                    return content
                except McpError as error:
                    if error.error.code == CONNECTION_CLOSED:
                        raise MarketplaceMCPTransportError(
                            "Marketplace MCP connection closed"
                        ) from error
                    raise MarketplaceMCPError("Marketplace MCP protocol error") from error
    except* (
        MarketplaceMCPTransportError,
        TimeoutError,
        OSError,
        EOFError,
        anyio.BrokenResourceError,
        anyio.ClosedResourceError,
    ) as error:
        raise MarketplaceMCPTransportError("Marketplace MCP connection failed") from error
    except* MarketplaceMCPError as error:
        raise MarketplaceMCPError("Marketplace MCP failed or is unavailable") from error


async def _call_once(
    tool: Literal["search_jobs", "get_job"], argument: str
) -> list[SampleJob] | SampleJob | None:
    arguments = {"query": argument} if tool == "search_jobs" else {"job_id": argument}
    content = await _call_tool("job_inbox", tool, arguments)
    try:
        if tool == "search_jobs":
            return TypeAdapter(list[SampleJob]).validate_python(content["result"])
        return JobLookupResult.model_validate(content).job
    except (ValidationError, KeyError) as error:
        raise MarketplaceMCPError("Marketplace MCP returned invalid data") from error


async def search_jobs(query: str) -> list[SampleJob]:
    result = await retry_transport(
        lambda: _call_once("search_jobs", query),
        MarketplaceMCPTransportError,
        MarketplaceMCPError,
        "Marketplace",
    )
    assert isinstance(result, list)
    return result


async def get_job(job_id: str) -> SampleJob | None:
    result = await retry_transport(
        lambda: _call_once("get_job", job_id),
        MarketplaceMCPTransportError,
        MarketplaceMCPError,
        "Marketplace",
    )
    assert result is None or isinstance(result, SampleJob)
    return result


async def _read_model(caller: str, tool: str, arguments: dict[str, Any], model: type[BaseModel]):
    async def read():
        content = await _call_tool(caller, tool, arguments)
        try:
            return model.model_validate(content)
        except ValidationError as error:
            raise MarketplaceMCPError(f"Marketplace MCP {tool} returned invalid data") from error

    return await retry_transport(
        read, MarketplaceMCPTransportError, MarketplaceMCPError, "Marketplace"
    )


async def get_client_history(client_id: str) -> ClientHistory:
    result = await _read_model(
        "risk_assessor", "get_client_history", {"client_id": client_id}, ClientHistory
    )
    assert isinstance(result, ClientHistory)
    if result.client_id != client_id:
        raise MarketplaceMCPError("Marketplace MCP returned a mismatched client history")
    return result


async def get_marketplace_policy() -> MarketplacePolicy:
    result = await _read_model("policy_reader", "get_marketplace_policy", {}, MarketplacePolicy)
    assert isinstance(result, MarketplacePolicy)
    if any(not phrase.strip() for phrase in result.banned_phrases):
        raise MarketplaceMCPError("Marketplace MCP returned an invalid banned phrase")
    return result


async def list_messages(proposal_id: str | None = None) -> list[MarketplaceMessage]:
    async def read() -> list[MarketplaceMessage]:
        content = await _call_tool("message_inbox", "list_messages", {"proposal_id": proposal_id})
        try:
            messages = TypeAdapter(list[MarketplaceMessage]).validate_python(content["result"])
        except (ValidationError, KeyError) as error:
            raise MarketplaceMCPError("Marketplace MCP returned invalid messages") from error
        if proposal_id is not None and any(item.proposal_id != proposal_id for item in messages):
            raise MarketplaceMCPError("Marketplace MCP returned messages for another proposal")
        return messages

    return await retry_transport(
        read, MarketplaceMCPTransportError, MarketplaceMCPError, "Marketplace"
    )


async def get_connects_balance() -> ConnectsBalance:
    result = await _read_model("pipeline_viewer", "get_connects_balance", {}, ConnectsBalance)
    assert isinstance(result, ConnectsBalance)
    return result


async def list_proposals() -> list[PipelineProposal]:
    async def read() -> list[PipelineProposal]:
        content = await _call_tool("pipeline_viewer", "list_proposals", {})
        try:
            return TypeAdapter(list[PipelineProposal]).validate_python(content["result"])
        except (ValidationError, KeyError) as error:
            raise MarketplaceMCPError("Marketplace MCP returned invalid proposals") from error

    return await retry_transport(
        read, MarketplaceMCPTransportError, MarketplaceMCPError, "Marketplace"
    )


async def _create_draft_once(arguments: dict[str, Any]) -> ProposalDraftResult:
    content = await _call_tool("proposal_publisher", "create_proposal_draft", arguments)
    try:
        return ProposalDraftResult.model_validate(content)
    except ValidationError as error:
        raise MarketplaceMCPError("Marketplace MCP returned invalid data") from error


async def create_proposal_draft(
    *,
    job_id: str,
    cover_letter: str,
    price: float,
    idempotency_key: str,
    screening_answers: list[str] | None = None,
    dry_run: bool = True,
    trace_id: str | None = None,
) -> ProposalDraftResult:
    """Retries are safe: the server deduplicates writes by idempotency key."""
    arguments: dict[str, Any] = {
        "job_id": job_id,
        "cover_letter": cover_letter,
        "price": price,
        "idempotency_key": idempotency_key,
        "dry_run": dry_run,
    }
    if screening_answers:
        arguments["screening_answers"] = screening_answers
    if trace_id is not None:
        arguments["trace_id"] = trace_id
    return await retry_transport(
        lambda: _create_draft_once(arguments),
        MarketplaceMCPTransportError,
        MarketplaceMCPError,
        "Marketplace",
    )
