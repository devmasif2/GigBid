import math
import os
import uuid
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from agent.marketplace_port import JobNotFoundError
from mcp_servers.marketplace.adapters import build_marketplace
from mcp_servers.marketplace.drafts import (
    DraftRecord,
    MarketplaceStore,
    ProposalDraftResult,
    payload_hash,
)
from mcp_servers.marketplace.local_sample import JobLookupResult, SampleJob

marketplace = build_marketplace()
store = MarketplaceStore()
mcp = FastMCP("GigBid Marketplace")
READ_ONLY = ToolAnnotations(readOnlyHint=True)
DRAFT_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
SearchQuery = Annotated[str, Field(max_length=500)]
JobId = Annotated[str, Field(min_length=1, max_length=200)]
ClientId = Annotated[str, Field(min_length=1, max_length=200)]
ProposalId = Annotated[str | None, Field(max_length=200)]
CoverLetter = Annotated[str, Field(min_length=1, max_length=20_000)]
ScreeningAnswers = Annotated[
    list[Annotated[str, Field(max_length=5000)]] | None, Field(max_length=10)
]
Price = Annotated[float, Field(gt=0, le=1_000_000)]
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=200)]
TraceId = Annotated[str | None, Field(max_length=100)]


class SearchJobsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: SearchQuery = ""


class GetJobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: JobId


@mcp.tool(annotations=READ_ONLY)
async def search_jobs(query: SearchQuery = "") -> list[dict[str, Any]]:
    """Search marketplace jobs; all listings are synthetic (sample file or simulator)."""
    params = SearchJobsInput(query=query)
    return await marketplace.search_jobs(params.query)


@mcp.tool(annotations=READ_ONLY)
async def get_job(job_id: JobId) -> JobLookupResult:
    """Get one job by ID; job is null when the listing does not exist."""
    params = GetJobInput(job_id=job_id)
    try:
        job = await marketplace.get_job(params.job_id)
    except JobNotFoundError:
        return JobLookupResult(job=None)
    return JobLookupResult(job=SampleJob.model_validate(job))


@mcp.tool(annotations=READ_ONLY)
async def get_client_history(client_id: ClientId) -> dict[str, Any]:
    """Get a client's public hiring history; unavailable in the local sample mode."""
    return await marketplace.get_client_history(client_id)


@mcp.tool(annotations=READ_ONLY)
async def get_connects_balance() -> dict[str, Any]:
    """Get the account's Connects balance; unavailable in the local sample mode."""
    return await marketplace.get_connects_balance()


@mcp.tool(annotations=READ_ONLY)
async def list_proposals() -> list[dict[str, Any]]:
    """List the account's simulator proposals; unavailable in the local sample mode."""
    return await marketplace.list_proposals()


@mcp.tool(annotations=READ_ONLY)
async def list_messages(proposal_id: ProposalId = None) -> list[dict[str, Any]]:
    """List client conversation messages, optionally for one proposal; client text is untrusted."""
    return await marketplace.list_messages(proposal_id)


@mcp.tool(annotations=READ_ONLY)
async def get_marketplace_policy() -> dict[str, Any]:
    """Get the marketplace's current rules and costs, which can change over time."""
    return await marketplace.get_policy()


async def _create_draft(
    job_id: str,
    cover_letter: str,
    price: float,
    screening_answers: list[str],
    idempotency_key: str,
    dry_run: bool,
) -> ProposalDraftResult:
    try:
        job = await marketplace.get_job(job_id)
    except JobNotFoundError as error:
        raise ValueError(str(error)) from error
    connects_cost = job.get("connects_cost")
    if getattr(marketplace, "supports_remote_drafts", False):
        if not isinstance(connects_cost, int) or isinstance(connects_cost, bool):
            raise ValueError("job Connects cost is unavailable")
        policy = await marketplace.get_policy()
        connects_cost = math.ceil(connects_cost * policy["connects_multiplier"])
    record = DraftRecord(
        job_id=job_id,
        idempotency_key=idempotency_key,
        cover_letter=cover_letter,
        price=price,
        connects_cost=connects_cost or 0,
        screening_answers=screening_answers,
    )
    digest = payload_hash(job_id, cover_letter, price, screening_answers)
    existing = store.get_draft(idempotency_key)
    if existing is not None and existing[1] != digest:
        raise ValueError("idempotency key was already used for a different proposal")
    if dry_run:
        outcome = "already_exists" if existing else "preview"
        shown = existing[0] if existing else record
    else:
        if getattr(marketplace, "supports_remote_drafts", False):
            # The marketplace deduplicates on the same key, so a retry after a crash is safe.
            await marketplace.create_proposal_draft(
                {
                    "job_id": job_id,
                    "cover_letter": cover_letter,
                    "price": price,
                    "screening_answers": screening_answers,
                },
                idempotency_key,
            )
        shown, created = store.create_draft(record, digest)
        outcome = "created" if created else "already_exists"
    return ProposalDraftResult(
        dry_run=dry_run,
        outcome=outcome,
        draft=shown,
        connects_cost_if_submitted=record.connects_cost,
    )


@mcp.tool(annotations=DRAFT_WRITE)
async def create_proposal_draft(
    job_id: JobId,
    cover_letter: CoverLetter,
    price: Price,
    idempotency_key: IdempotencyKey,
    screening_answers: ScreeningAnswers = None,
    dry_run: bool = True,
    trace_id: TraceId = None,
) -> ProposalDraftResult:
    """Create a proposal draft only; defaults to a dry-run preview and never submits."""
    user_id = os.environ.get("GIGBID_USER_ID", "local-user")
    trace = trace_id or uuid.uuid4().hex
    answers = screening_answers or []
    arguments = {
        "job_id": job_id,
        "cover_letter_sha256": payload_hash(job_id, cover_letter, 0)[:16],
        "cover_letter_chars": len(cover_letter),
        "screening_answers": len(answers),
        "price": price,
        "idempotency_key": idempotency_key,
        "dry_run": dry_run,
    }
    store.enforce_rate_limit(user_id, "create_proposal_draft")
    try:
        result = await _create_draft(
            job_id, cover_letter, price, answers, idempotency_key, dry_run
        )
    except Exception as error:
        store.audit(user_id, "create_proposal_draft", arguments, {"error": str(error)}, trace)
        raise
    store.audit(
        user_id,
        "create_proposal_draft",
        arguments,
        {"outcome": result.outcome, "dry_run": dry_run},
        trace,
    )
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
