from fastapi import APIRouter, HTTPException, Path, Query

from agent import marketplace_mcp_client
from agent.marketplace_mcp_client import MarketplaceMCPError
from mcp_servers.marketplace.local_sample import SampleJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "",
    response_model=list[SampleJob],
    responses={503: {"description": "Local sample marketplace unavailable"}},
)
async def list_jobs(
    query: str = Query(default="", max_length=500),
) -> list[SampleJob]:
    try:
        return await marketplace_mcp_client.search_jobs(query)
    except MarketplaceMCPError as error:
        raise HTTPException(
            status_code=503, detail="local sample marketplace is unavailable"
        ) from error


@router.get(
    "/{job_id}",
    response_model=SampleJob,
    responses={
        404: {"description": "Job not found"},
        503: {"description": "Local sample marketplace unavailable"},
    },
)
async def get_job(job_id: str = Path(min_length=1, max_length=200)) -> SampleJob:
    try:
        job = await marketplace_mcp_client.get_job(job_id)
    except MarketplaceMCPError as error:
        raise HTTPException(
            status_code=503, detail="local sample marketplace is unavailable"
        ) from error
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
