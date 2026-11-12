import json
import sqlite3
from contextlib import closing

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolAnnotations

from mcp_servers.marketplace import server
from mcp_servers.marketplace.drafts import MarketplaceStore
from mcp_servers.marketplace.local_sample import LocalSampleMarketplace

JOB = {
    "job_id": "job-1",
    "title": "Python task",
    "description": "Write Python",
    "required_skills": ["Python"],
    "budget": {"min": 100, "max": 200, "currency": "USD"},
    "duration_days": 3,
    "screening_questions": [],
    "warning_signals": [],
    "connects_cost": 6,
}
LETTER = "Private cover letter text that must not be copied into the audit log."


@pytest.fixture
def database(tmp_path, monkeypatch):
    jobs_path = tmp_path / "jobs.json"
    jobs_path.write_text(json.dumps([JOB]), encoding="utf-8")
    db_path = tmp_path / "marketplace.sqlite3"
    monkeypatch.setattr(server, "marketplace", LocalSampleMarketplace(jobs_path))
    monkeypatch.setattr(server, "store", MarketplaceStore(db_path, rate_limit_per_minute=5))
    return db_path


def _args(**overrides):
    return {
        "job_id": "job-1",
        "cover_letter": LETTER,
        "price": 150,
        "idempotency_key": "bid-key-0001",
        **overrides,
    }


def _rows(db_path, table):
    with closing(sqlite3.connect(db_path)) as connection:
        return connection.execute(f"SELECT * FROM {table}").fetchall()


@pytest.mark.anyio
async def test_tool_declares_safe_write_annotations_and_constraints(database):
    async with create_connected_server_and_client_session(server.mcp) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    tool = tools["create_proposal_draft"]
    assert tool.annotations == ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )
    properties = tool.inputSchema["properties"]
    assert properties["dry_run"]["default"] is True
    assert properties["idempotency_key"]["minLength"] == 8
    assert properties["price"]["exclusiveMinimum"] == 0
    assert "outputSchema" in tool.model_dump(by_alias=True)


@pytest.mark.anyio
async def test_dry_run_is_default_and_writes_nothing_but_an_audit_entry(database):
    async with create_connected_server_and_client_session(server.mcp) as client:
        result = await client.call_tool("create_proposal_draft", _args())

    content = result.structuredContent
    assert result.isError is False
    assert content["dry_run"] is True
    assert content["outcome"] == "preview"
    assert content["connects_cost_if_submitted"] == 6
    assert content["connects_spent"] == 0
    assert content["external_action_taken"] is False
    assert _rows(database, "proposal_drafts") == []
    assert len(_rows(database, "audit_log")) == 1


@pytest.mark.anyio
async def test_retry_with_same_key_creates_exactly_one_draft(database):
    async with create_connected_server_and_client_session(server.mcp) as client:
        first = await client.call_tool("create_proposal_draft", _args(dry_run=False))
        retry = await client.call_tool("create_proposal_draft", _args(dry_run=False))
        preview = await client.call_tool("create_proposal_draft", _args())

    assert first.structuredContent["outcome"] == "created"
    assert retry.structuredContent["outcome"] == "already_exists"
    assert preview.structuredContent["outcome"] == "already_exists"
    assert len(_rows(database, "proposal_drafts")) == 1


@pytest.mark.anyio
async def test_reused_key_with_different_payload_is_rejected(database):
    async with create_connected_server_and_client_session(server.mcp) as client:
        await client.call_tool("create_proposal_draft", _args(dry_run=False))
        conflict = await client.call_tool(
            "create_proposal_draft", _args(dry_run=False, price=999)
        )
        conflict_preview = await client.call_tool("create_proposal_draft", _args(price=999))

    assert conflict.isError is True
    assert conflict_preview.isError is True
    assert len(_rows(database, "proposal_drafts")) == 1


@pytest.mark.anyio
async def test_unknown_job_and_invalid_inputs_do_not_write(database):
    async with create_connected_server_and_client_session(server.mcp) as client:
        unknown = await client.call_tool(
            "create_proposal_draft", _args(job_id="missing", dry_run=False)
        )
        bad_price = await client.call_tool("create_proposal_draft", _args(price=0))
        short_key = await client.call_tool(
            "create_proposal_draft", _args(idempotency_key="short")
        )

    assert unknown.isError and bad_price.isError and short_key.isError
    assert _rows(database, "proposal_drafts") == []


@pytest.mark.anyio
async def test_audit_log_records_trace_without_private_text_and_is_append_only(database):
    async with create_connected_server_and_client_session(server.mcp) as client:
        await client.call_tool(
            "create_proposal_draft", _args(dry_run=False, trace_id="trace-abc")
        )

    (row,) = _rows(database, "audit_log")
    _, _, user_id, tool, arguments, result, trace_id = row
    assert (user_id, tool, trace_id) == ("local-user", "create_proposal_draft", "trace-abc")
    assert LETTER not in arguments
    assert json.loads(arguments)["cover_letter_chars"] == len(LETTER)
    assert json.loads(result) == {"dry_run": False, "outcome": "created"}
    with closing(sqlite3.connect(database)) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("UPDATE audit_log SET user_id = 'other'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute("DELETE FROM audit_log")


@pytest.mark.anyio
async def test_per_user_rate_limit_blocks_excess_writes(database, monkeypatch):
    monkeypatch.setenv("GIGBID_USER_ID", "user-a")
    async with create_connected_server_and_client_session(server.mcp) as client:
        results = [
            await client.call_tool("create_proposal_draft", _args()) for _ in range(5)
        ]
        limited = await client.call_tool("create_proposal_draft", _args())
        monkeypatch.setenv("GIGBID_USER_ID", "user-b")
        other_user = await client.call_tool("create_proposal_draft", _args())

    assert all(result.isError is False for result in results)
    assert limited.isError is True
    assert other_user.isError is False
    assert len(_rows(database, "audit_log")) == 6
