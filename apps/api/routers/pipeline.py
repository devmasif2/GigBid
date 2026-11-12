from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.marketplace_mcp_client import (
    MarketplaceMCPError,
    PipelineProposal,
    get_connects_balance,
    list_proposals,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


class PipelineSnapshot(BaseModel):
    connects_balance: int
    proposals: list[PipelineProposal]


@router.get("", response_model=PipelineSnapshot)
async def get_pipeline() -> PipelineSnapshot:
    try:
        proposals = await list_proposals()
        balance = await get_connects_balance()
    except MarketplaceMCPError as error:
        raise HTTPException(
            status_code=503, detail="Simulator pipeline is unavailable."
        ) from error
    return PipelineSnapshot(connects_balance=balance.balance, proposals=proposals)
