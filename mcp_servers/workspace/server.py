from datetime import datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from mcp_servers.workspace.local_mock import LocalWorkspace

workspace = LocalWorkspace()
mcp = FastMCP("GigBid Workspace (local mock)")
READ_ONLY = ToolAnnotations(readOnlyHint=True)
IDEMPOTENT_DRAFT_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True
)
ShortText = Annotated[str, Field(min_length=1, max_length=200)]
DraftBody = Annotated[str, Field(min_length=1, max_length=20_000)]


class FreeSlotsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class HoldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: datetime
    idempotency_key: ShortText


class EmailDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: ShortText
    subject: ShortText
    body: DraftBody
    idempotency_key: ShortText


@mcp.tool(annotations=READ_ONLY)
def get_free_slots(start: datetime, end: datetime) -> list[str]:
    """List local mock calendar slots; this does not query an external calendar."""
    params = FreeSlotsInput(start=start, end=end)
    return [
        slot.isoformat()
        for slot in workspace.free_slots(params.start, params.end)
    ]


@mcp.tool(annotations=IDEMPOTENT_DRAFT_WRITE)
def create_tentative_hold(
    slot: datetime, idempotency_key: ShortText
) -> dict[str, Any]:
    """Create an idempotent tentative hold in the local mock calendar; no external event is created."""
    params = HoldInput(slot=slot, idempotency_key=idempotency_key)
    return workspace.create_tentative_hold(
        params.slot, params.idempotency_key
    ).model_dump(mode="json")


@mcp.tool(annotations=IDEMPOTENT_DRAFT_WRITE)
def create_email_draft(
    conversation_id: ShortText,
    subject: ShortText,
    body: DraftBody,
    idempotency_key: ShortText,
) -> dict[str, Any]:
    """Save an idempotent local email draft; this tool never sends email."""
    params = EmailDraftInput(
        conversation_id=conversation_id,
        subject=subject,
        body=body,
        idempotency_key=idempotency_key,
    )
    return workspace.create_email_draft(
        params.conversation_id,
        params.subject,
        params.body,
        params.idempotency_key,
    ).model_dump(mode="json")


if __name__ == "__main__":
    mcp.run(transport="stdio")
