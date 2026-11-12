from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from agent.mcp_client import PortfolioMCPError, retrieve_portfolio_evidence
from mcp_servers.portfolio.service import EvidenceItem

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/search", response_model=list[EvidenceItem])
async def search_portfolio(
    query: Annotated[str, Query(min_length=1, max_length=500)],
) -> list[EvidenceItem]:
    if not query.strip():
        raise HTTPException(status_code=422, detail="Search query must not be blank.")
    try:
        results = await retrieve_portfolio_evidence([query.strip()], caller="portfolio_viewer")
    except PortfolioMCPError as error:
        raise HTTPException(status_code=503, detail="Portfolio search is unavailable.") from error
    return results[0]
