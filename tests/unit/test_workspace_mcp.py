from datetime import UTC, datetime, timedelta

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolAnnotations

from mcp_servers.workspace import server
from mcp_servers.workspace.local_mock import LocalWorkspace


@pytest.fixture
def workspace():
    slots = [
        datetime(2026, 11, 12, 10, tzinfo=UTC),
        datetime(2026, 11, 12, 14, tzinfo=UTC),
    ]
    return LocalWorkspace(slots)


def test_tentative_hold_is_idempotent_and_removes_slot(workspace):
    slot = datetime(2026, 11, 12, 10, tzinfo=UTC)

    first = workspace.create_tentative_hold(slot, "hold-1")
    retry = workspace.create_tentative_hold(slot, "hold-1")

    assert first == retry
    assert workspace.free_slots(slot - timedelta(hours=1), slot + timedelta(hours=1)) == []


def test_hold_rejects_reused_key_for_another_slot(workspace):
    first = datetime(2026, 11, 12, 10, tzinfo=UTC)
    second = datetime(2026, 11, 12, 14, tzinfo=UTC)
    workspace.create_tentative_hold(first, "hold-1")

    with pytest.raises(ValueError, match="different slot"):
        workspace.create_tentative_hold(second, "hold-1")


def test_hold_rejects_unavailable_or_already_held_slot(workspace):
    slot = datetime(2026, 11, 12, 10, tzinfo=UTC)
    workspace.create_tentative_hold(slot, "hold-1")

    with pytest.raises(ValueError, match="already held"):
        workspace.create_tentative_hold(slot, "hold-2")
    with pytest.raises(ValueError, match="not in the local calendar"):
        workspace.create_tentative_hold(datetime(2026, 11, 13, 10, tzinfo=UTC), "hold-3")


def test_email_draft_is_idempotent_and_never_sent(workspace):
    draft = workspace.create_email_draft(
        "conversation-1", "Follow-up", "Thanks for your time.", "draft-1"
    )
    retry = workspace.create_email_draft(
        "conversation-1", "Follow-up", "Thanks for your time.", "draft-1"
    )

    assert draft == retry
    assert draft.status == "draft"


@pytest.mark.anyio
async def test_workspace_mcp_registers_read_and_idempotent_draft_tools(
    workspace, monkeypatch
):
    monkeypatch.setattr(server, "workspace", workspace)
    async with create_connected_server_and_client_session(server.mcp) as client:
        tools = await client.list_tools()
        slots = await client.call_tool(
            "get_free_slots",
            {
                "start": "2026-11-12T00:00:00+00:00",
                "end": "2026-11-12T23:59:59+00:00",
            },
        )
        hold = await client.call_tool(
            "create_tentative_hold",
            {
                "slot": "2026-11-12T10:00:00+00:00",
                "idempotency_key": "mcp-hold",
            },
        )
        email = await client.call_tool(
            "create_email_draft",
            {
                "conversation_id": "conversation-1",
                "subject": "Follow-up",
                "body": "Please review this draft.",
                "idempotency_key": "mcp-email",
            },
        )
        invalid_email = await client.call_tool(
            "create_email_draft",
            {
                "conversation_id": "conversation-1",
                "subject": "",
                "body": "Please review this draft.",
                "idempotency_key": "invalid-email",
            },
        )

    tool_by_name = {tool.name: tool for tool in tools.tools}
    assert set(tool_by_name) == {
        "get_free_slots",
        "create_tentative_hold",
        "create_email_draft",
    }
    assert tool_by_name["get_free_slots"].annotations.readOnlyHint is True
    assert (
        tool_by_name["create_tentative_hold"].annotations
        == ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=True
        )
    )
    hold_schema = tool_by_name["create_tentative_hold"].inputSchema["properties"]
    email_schema = tool_by_name["create_email_draft"].inputSchema["properties"]
    assert hold_schema["idempotency_key"]["minLength"] == 1
    assert hold_schema["idempotency_key"]["maxLength"] == 200
    assert email_schema["subject"]["minLength"] == 1
    assert email_schema["subject"]["maxLength"] == 200
    assert email_schema["body"]["maxLength"] == 20_000
    assert len(slots.structuredContent["result"]) == 2
    assert hold.structuredContent["status"] == "tentative"
    assert email.structuredContent["status"] == "draft"
    assert invalid_email.isError is True
