"""Restricted MCP client for the bid graph's portfolio evidence retrieval."""

import logging
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal, TypeVar

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED
from pydantic import TypeAdapter, ValidationError

from agent.tool_policy import call_allowed_tool, require_tool_access
from mcp_servers.portfolio.service import EvidenceItem


class PortfolioMCPError(RuntimeError):
    """Portfolio MCP could not provide valid evidence."""


class PortfolioMCPTransportError(PortfolioMCPError):
    """A temporary connection or timeout failure occurred."""


_LOGGER = logging.getLogger(__name__)
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.1
_TIMEOUT_SECONDS = 10
T = TypeVar("T")


async def retry_transport(
    operation: Callable[[], Awaitable[T]],
    transport_error: type[Exception],
    final_error: type[Exception],
    service: str,
) -> T:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return await operation()
        except transport_error as error:
            if attempt == _MAX_ATTEMPTS - 1:
                _LOGGER.warning("%s MCP unavailable after %d attempts", service, _MAX_ATTEMPTS)
                raise final_error(f"{service} MCP failed or is unavailable") from error
            delay = _BACKOFF_SECONDS * (2**attempt)
            _LOGGER.warning(
                "%s MCP connection failed on attempt %d; retrying in %.1fs",
                service, attempt + 1, delay,
            )
            await anyio.sleep(delay)
    raise AssertionError("unreachable")


async def retrieve_portfolio_evidence(
    requirements: list[str], portfolio_path: Path | None = None, *,
    caller: Literal["fit_matcher", "portfolio_viewer"] = "fit_matcher",
) -> list[list[EvidenceItem]]:
    if not requirements:
        return []

    return await retry_transport(
        lambda: _retrieve_once(requirements, portfolio_path, caller),
        PortfolioMCPTransportError,
        PortfolioMCPError,
        "Portfolio",
    )


async def _retrieve_once(
    requirements: list[str], portfolio_path: Path | None, caller: str
) -> list[list[EvidenceItem]]:
    require_tool_access(caller, "portfolio", "search_evidence")
    env = os.environ.copy()
    if portfolio_path is not None:
        env["GIGBID_PORTFOLIO_PATH"] = str(portfolio_path.resolve())
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.portfolio.server"],
        env=env,
    )
    adapter = TypeAdapter(list[EvidenceItem])
    try:
        timeout = 120 if os.environ.get("GIGBID_PORTFOLIO_SEARCH") == "ollama_hybrid" else _TIMEOUT_SECONDS
        with anyio.fail_after(timeout):
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                try:
                    await session.initialize()
                    results = []
                    for requirement in requirements:
                        response = await call_allowed_tool(
                            session,
                            caller=caller,
                            server="portfolio",
                            tool="search_evidence",
                            arguments={"requirement": requirement, "k": 5},
                        )
                        if response.isError:
                            raise PortfolioMCPError("Portfolio MCP search_evidence failed")
                        content = response.structuredContent
                        if not isinstance(content, dict) or "result" not in content:
                            raise PortfolioMCPError("Portfolio MCP returned invalid evidence")
                        try:
                            results.append(adapter.validate_python(content["result"]))
                        except ValidationError as error:
                            raise PortfolioMCPError(
                                "Portfolio MCP returned invalid evidence"
                            ) from error
                    return results
                except McpError as error:
                    if error.error.code == CONNECTION_CLOSED:
                        raise PortfolioMCPTransportError(
                            "Portfolio MCP connection closed"
                        ) from error
                    raise PortfolioMCPError("Portfolio MCP protocol error") from error
    except* (
        PortfolioMCPTransportError,
        TimeoutError,
        OSError,
        EOFError,
        anyio.BrokenResourceError,
        anyio.ClosedResourceError,
    ) as error:
        raise PortfolioMCPTransportError("Portfolio MCP connection failed") from error
    except* PortfolioMCPError as error:
        raise PortfolioMCPError("Portfolio MCP failed or is unavailable") from error
