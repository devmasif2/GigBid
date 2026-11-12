from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import anyio
import pytest
from mcp.shared.exceptions import McpError
from mcp.types import CONNECTION_CLOSED, INVALID_PARAMS, CallToolResult, ErrorData

from agent import mcp_client
from agent.mcp_client import PortfolioMCPError, PortfolioMCPTransportError


@pytest.mark.anyio
async def test_retries_transient_failures_with_bounded_backoff(monkeypatch):
    expected = [[]]
    retrieve = AsyncMock(
        side_effect=[
            PortfolioMCPTransportError("closed"),
            PortfolioMCPTransportError("closed"),
            expected,
        ]
    )
    sleep = AsyncMock()
    monkeypatch.setattr(mcp_client, "_retrieve_once", retrieve)
    monkeypatch.setattr(mcp_client.anyio, "sleep", sleep)

    assert await mcp_client.retrieve_portfolio_evidence(["Python"]) == expected
    assert retrieve.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [0.1, 0.2]


@pytest.mark.anyio
async def test_retry_exhaustion_raises_explicit_error(monkeypatch):
    retrieve = AsyncMock(side_effect=PortfolioMCPTransportError("closed"))
    sleep = AsyncMock()
    monkeypatch.setattr(mcp_client, "_retrieve_once", retrieve)
    monkeypatch.setattr(mcp_client.anyio, "sleep", sleep)

    with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
        await mcp_client.retrieve_portfolio_evidence(["Python"])
    assert retrieve.await_count == 3
    assert sleep.await_count == 2


@pytest.mark.anyio
async def test_tool_error_is_not_retried(monkeypatch):
    retrieve = AsyncMock(side_effect=PortfolioMCPError("invalid evidence"))
    monkeypatch.setattr(mcp_client, "_retrieve_once", retrieve)

    with pytest.raises(PortfolioMCPError, match="invalid evidence"):
        await mcp_client.retrieve_portfolio_evidence(["Python"])
    assert retrieve.await_count == 1


@pytest.mark.anyio
async def test_real_call_tool_error_is_not_retried(monkeypatch):
    calls = []

    @asynccontextmanager
    async def fake_stdio(_params):
        yield None, None

    class FakeSession:
        def __init__(self, _read, _write):
            calls.append("opened")

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

        async def initialize(self):
            pass

        async def call_tool(self, name, arguments):
            assert name == "search_evidence"
            assert arguments == {"requirement": "Python", "k": 5}
            return CallToolResult(content=[], isError=True)

    monkeypatch.setattr(mcp_client, "stdio_client", fake_stdio)
    monkeypatch.setattr(mcp_client, "ClientSession", FakeSession)
    with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
        await mcp_client.retrieve_portfolio_evidence(["Python"])
    assert calls == ["opened"]


@pytest.mark.anyio
async def test_timeout_during_server_startup_retries(monkeypatch):
    attempts = []

    @asynccontextmanager
    async def slow_stdio(_params):
        attempts.append("opened")
        await anyio.sleep_forever()
        yield None, None

    monkeypatch.setattr(mcp_client, "stdio_client", slow_stdio)
    monkeypatch.setattr(mcp_client, "_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(mcp_client, "_BACKOFF_SECONDS", 0)
    with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
        await mcp_client.retrieve_portfolio_evidence(["Python"])
    assert len(attempts) == 3


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "attempts"),
    [(CONNECTION_CLOSED, 3), (INVALID_PARAMS, 1)],
)
async def test_mcp_protocol_errors_are_classified(monkeypatch, code, attempts):
    calls = []

    @asynccontextmanager
    async def fake_stdio(_params):
        yield None, None

    class FakeSession:
        def __init__(self, _read, _write):
            calls.append("opened")

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

        async def initialize(self):
            raise McpError(ErrorData(code=code, message="test protocol error"))

    monkeypatch.setattr(mcp_client, "stdio_client", fake_stdio)
    monkeypatch.setattr(mcp_client, "ClientSession", FakeSession)
    monkeypatch.setattr(mcp_client, "_BACKOFF_SECONDS", 0)
    with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
        await mcp_client.retrieve_portfolio_evidence(["Python"])
    assert len(calls) == attempts


@pytest.mark.anyio
async def test_malformed_evidence_is_not_retried(monkeypatch):
    calls = []

    @asynccontextmanager
    async def fake_stdio(_params):
        yield None, None

    class FakeSession:
        def __init__(self, _read, _write):
            calls.append("opened")

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback):
            return False

        async def initialize(self):
            pass

        async def call_tool(self, _name, _arguments):
            return CallToolResult(
                content=[], structuredContent={"result": [{"id": "missing-fields"}]}
            )

    monkeypatch.setattr(mcp_client, "stdio_client", fake_stdio)
    monkeypatch.setattr(mcp_client, "ClientSession", FakeSession)
    with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
        await mcp_client.retrieve_portfolio_evidence(["Python"])
    assert calls == ["opened"]


@pytest.mark.anyio
async def test_empty_requirements_do_not_start_server(monkeypatch):
    retrieve = AsyncMock()
    monkeypatch.setattr(mcp_client, "_retrieve_once", retrieve)

    assert await mcp_client.retrieve_portfolio_evidence([]) == []
    retrieve.assert_not_awaited()
