"""REST API for the local GigSim stand-in. See gigsim_local/README.md for the contract."""

import secrets
import time
from collections import deque
from collections.abc import Callable
from typing import Annotated, Any, TypeAlias

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from gigsim_local.engine import Account, SimConfig, SimError, Simulator

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=200)]


class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=200)
    cover_letter: str = Field(min_length=1, max_length=20_000)
    price: float = Field(gt=0, le=1_000_000)
    screening_answers: list[Annotated[str, Field(max_length=5000)]] = Field(
        default_factory=list, max_length=10
    )


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: int = Field(ge=1, le=720)


class FaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fail_next: int = Field(default=0, ge=0, le=100)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)


def create_app(
    config: SimConfig | None = None, time_fn: Callable[[], float] = time.monotonic
) -> FastAPI:
    sim = Simulator(config or SimConfig.from_env())
    app = FastAPI(title="GigSim (local stand-in)", version="0.1.0")
    app.state.sim = sim
    windows: dict[str, deque[float]] = {}

    @app.exception_handler(SimError)
    async def sim_error_handler(_: Request, error: SimError) -> JSONResponse:
        return JSONResponse(
            {"detail": error.detail}, status_code=error.status, headers=error.headers
        )

    def bearer(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise SimError(401, "missing bearer token", {"WWW-Authenticate": "Bearer"})
        return authorization.removeprefix("Bearer ").strip()

    def current_account(authorization: Annotated[str | None, Header()] = None) -> Account:
        token = bearer(authorization)
        user_id = None
        for known, owner in sim.config.user_tokens.items():
            if secrets.compare_digest(known, token):
                user_id = owner
        if user_id is None:
            raise SimError(401, "invalid bearer token", {"WWW-Authenticate": "Bearer"})
        now = time_fn()
        window = windows.setdefault(user_id, deque())
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= sim.config.rate_limit_per_minute:
            retry_after = max(1, int(60 - (now - window[0])) + 1)
            raise SimError(429, "rate limit exceeded", {"Retry-After": str(retry_after)})
        window.append(now)
        if sim.should_fail():
            raise SimError(503, "simulated outage", {"Retry-After": "1"})
        return sim.account(user_id)

    def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
        token = bearer(authorization)
        if not secrets.compare_digest(sim.config.admin_token, token):
            raise SimError(403, "admin token required")

    UserAccount: TypeAlias = Annotated[Account, Depends(current_account)]
    Admin = Depends(require_admin)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "clock_hour": sim.clock, "simulator": "gigsim_local"}

    @app.get("/jobs")
    async def list_jobs(
        _: UserAccount,
        query: str = Query(default="", max_length=500),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        since_hour: int | None = None,
    ) -> list[dict[str, Any]]:
        return sim.list_jobs(query, limit, offset, since_hour)

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str, _: UserAccount) -> dict[str, Any]:
        return sim.get_job(job_id)

    @app.get("/clients/{client_id}/history")
    async def client_history(client_id: str, _: UserAccount) -> dict[str, Any]:
        return sim.client_history(client_id)

    @app.get("/account/connects")
    async def connects(account: UserAccount) -> dict[str, Any]:
        return {"balance": account.connects}

    @app.get("/policy")
    async def policy(_: UserAccount) -> dict[str, Any]:
        return sim.policy

    @app.post("/proposals")
    async def create_proposal(
        body: ProposalCreate, key: IdempotencyKey, account: UserAccount, response: Response
    ) -> dict[str, Any]:
        result, replay = sim.create_draft(account, key, body.model_dump())
        if replay:
            response.headers["Idempotent-Replay"] = "true"
        return result

    @app.get("/proposals")
    async def list_proposals(account: UserAccount, status: str | None = None) -> list[dict[str, Any]]:
        return sim.list_proposals(account, status)

    @app.get("/proposals/{proposal_id}")
    async def get_proposal(proposal_id: str, account: UserAccount) -> dict[str, Any]:
        return sim.get_proposal(account, proposal_id)

    @app.post("/proposals/{proposal_id}/confirm")
    async def confirm_proposal(
        proposal_id: str, key: IdempotencyKey, account: UserAccount, response: Response
    ) -> dict[str, Any]:
        result, replay = sim.confirm(account, proposal_id, key)
        if replay:
            response.headers["Idempotent-Replay"] = "true"
        return result

    @app.get("/messages")
    async def list_messages(
        account: UserAccount, proposal_id: str | None = None
    ) -> list[dict[str, Any]]:
        return sim.list_messages(account, proposal_id)

    @app.post("/messages")
    async def send_message(
        body: MessageCreate, key: IdempotencyKey, account: UserAccount, response: Response
    ) -> dict[str, Any]:
        result, replay = sim.send_message(account, key, body.model_dump())
        if replay:
            response.headers["Idempotent-Replay"] = "true"
        return result

    @app.get("/events")
    async def events(account: UserAccount, after_id: int = Query(default=0, ge=0)) -> list[dict]:
        return sim.events(account, after_id)

    @app.post("/sim/tick", dependencies=[Admin])
    async def tick(body: TickRequest) -> dict[str, Any]:
        return {"clock_hour": sim.tick(body.hours)}

    @app.post("/sim/faults", dependencies=[Admin])
    async def faults(body: FaultRequest) -> dict[str, Any]:
        sim.fail_next = body.fail_next
        sim.error_rate = body.error_rate
        return {"fail_next": sim.fail_next, "error_rate": sim.error_rate}

    @app.post("/sim/policy", dependencies=[Admin])
    async def update_policy(changes: dict[str, Any]) -> dict[str, Any]:
        return sim.update_policy(changes)

    @app.get("/sim/ground-truth", dependencies=[Admin])
    async def ground_truth() -> dict[str, Any]:
        return sim.ground_truth()

    @app.get("/sim/outcomes", dependencies=[Admin])
    async def outcomes() -> dict[str, Any]:
        counts: dict[str, int] = {}
        for account in sim.accounts.values():
            for proposal in account.proposals.values():
                counts[proposal["status"]] = counts.get(proposal["status"], 0) + 1
        submitted = sum(v for k, v in counts.items() if k != "draft")
        replied = sum(counts.get(k, 0) for k in ("replied", "interview", "hired"))
        return {
            "status_counts": counts,
            "submitted": submitted,
            "reply_rate": round(replied / submitted, 4) if submitted else None,
            "hire_rate": round(counts.get("hired", 0) / submitted, 4) if submitted else None,
        }

    @app.post("/sim/reset", dependencies=[Admin])
    async def reset() -> dict[str, Any]:
        sim.reset()
        windows.clear()
        return {"status": "reset"}

    return app

