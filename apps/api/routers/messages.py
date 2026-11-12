from fastapi import APIRouter, HTTPException, Query

from agent.marketplace_mcp_client import (
    MarketplaceMCPError,
    MarketplaceMessage,
    list_messages,
)

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("", response_model=list[MarketplaceMessage])
async def get_messages(
    proposal_id: str | None = Query(default=None, min_length=1, max_length=200),
) -> list[MarketplaceMessage]:
    try:
        return await list_messages(proposal_id)
    except MarketplaceMCPError as error:
        raise HTTPException(
            status_code=503, detail="Marketplace messages are unavailable."
        ) from error
