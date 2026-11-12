import json
import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from langgraph.types import Command
from mcp.shared.memory import create_connected_server_and_client_session

from agent import marketplace_mcp_client
from agent.graphs.bid_graph import build_bid_graph
from agent.marketplace_port import (
    JobNotFoundError,
    MarketplaceRateLimitedError,
    MarketplaceRejectedError,
    MarketplaceUnavailableError,
)
from apps.api.main import app as api_app
from gigsim_local.app import create_app
from gigsim_local.engine import SimConfig
from mcp_servers.marketplace import server
from mcp_servers.marketplace.adapters import build_marketplace
from mcp_servers.marketplace.adapters.gigsim import GigSimMarketplace
from mcp_servers.marketplace.drafts import MarketplaceStore
from mcp_servers.marketplace.local_sample import LocalSampleMarketplace
from mcp_servers.portfolio.service import Portfolio

TOKEN = "tok-a"
ADMIN = {"Authorization": "Bearer admin-secret"}


def sim_config(**overrides):
    values = {
        "seed": 11,
        "job_count": 60,
        "client_count": 12,
        "user_tokens": {TOKEN: "user-a"},
        "admin_token": "admin-secret",
        "rate_limit_per_minute": 1000,
    }
    return SimConfig(**{**values, **overrides})


@pytest.fixture
def sim_app():
    return create_app(sim_config())


@pytest.fixture
async def admin(sim_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sim_app), base_url="http://sim"
    ) as http:
        yield http


@pytest.fixture
async def adapter(sim_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sim_app), base_url="http://sim"
    ) as http:
        yield GigSimMarketplace(token=TOKEN, client=http)


def visible_job(sim_app):
    return next(j for j in sim_app.state.sim.jobs.values() if j["posted_at_hour"] <= 0)


# -- adapter: reads and error mapping --------------------------------------------------------
@pytest.mark.anyio
async def test_adapter_reads_through_the_marketplace_port(adapter, sim_app):
    job = visible_job(sim_app)

    found = await adapter.get_job(job["job_id"])
    history = await adapter.get_client_history(job["client_id"])
    balance = await adapter.get_connects_balance()
    policy = await adapter.get_policy()
    searched = await adapter.search_jobs(job["required_skills"][0])

    assert found["title"] == job["title"] and found["data_kind"] == "synthetic"
    assert history["client_id"] == job["client_id"]
    assert balance["balance"] == 200
    assert policy["version"] == 1 and policy["rules"]
    assert job["job_id"] in {j["job_id"] for j in searched}
    assert await adapter.list_messages() == []
    with pytest.raises(JobNotFoundError):
        await adapter.get_job("missing-job")


@pytest.mark.anyio
async def test_adapter_maps_http_failures_to_distinct_errors(sim_app, admin):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sim_app), base_url="http://sim"
    ) as http:
        good = GigSimMarketplace(token=TOKEN, client=http)
        with pytest.raises(MarketplaceUnavailableError, match="authentication"):
            await GigSimMarketplace(token="wrong", client=http).get_connects_balance()
        with pytest.raises(MarketplaceUnavailableError, match="GIGSIM_API_TOKEN"):
            await GigSimMarketplace(token="", client=http).get_connects_balance()
        with pytest.raises(MarketplaceRejectedError):
            await good.create_proposal_draft({"job_id": "missing", "cover_letter": "x", "price": 5}, "key-12345")

        await admin.post("/sim/faults", headers=ADMIN, json={"fail_next": 1})
        with pytest.raises(MarketplaceUnavailableError, match="server error"):
            await good.get_connects_balance()
        assert (await good.get_connects_balance())["balance"] == 200

    limited_app = create_app(sim_config(rate_limit_per_minute=1))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=limited_app), base_url="http://sim"
    ) as http:
        limited = GigSimMarketplace(token=TOKEN, client=http)
        await limited.get_connects_balance()
        with pytest.raises(MarketplaceRateLimitedError) as caught:
            await limited.get_connects_balance()
    assert caught.value.retry_after and caught.value.retry_after >= 1

    def refuse(_request):
        raise httpx.ConnectError("connection refused")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(refuse), base_url="http://sim"
    ) as http:
        with pytest.raises(MarketplaceUnavailableError, match="unreachable"):
            await GigSimMarketplace(token=TOKEN, client=http).get_connects_balance()


@pytest.mark.anyio
async def test_marketplace_mode_is_chosen_by_configuration(monkeypatch):
    assert isinstance(build_marketplace("sample"), LocalSampleMarketplace)
    assert isinstance(build_marketplace("gigsim"), GigSimMarketplace)
    monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "gigsim")
    assert isinstance(build_marketplace(), GigSimMarketplace)
    with pytest.raises(ValueError, match="unknown marketplace mode"):
        build_marketplace("upwork")


# -- MCP server in gigsim mode ---------------------------------------------------------------
@pytest.fixture
async def gigsim_mcp(sim_app, tmp_path, monkeypatch):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sim_app), base_url="http://sim"
    ) as http:
        monkeypatch.setattr(server, "marketplace", GigSimMarketplace(token=TOKEN, client=http))
        monkeypatch.setattr(server, "store", MarketplaceStore(tmp_path / "drafts.sqlite3"))
        yield server


def draft_args(job, **overrides):
    return {
        "job_id": job["job_id"],
        "cover_letter": "A tailored proposal for this project.",
        "price": 400,
        "idempotency_key": "draft-key-0001",
        "dry_run": False,
        **overrides,
    }


async def remote_drafts(sim_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=sim_app), base_url="http://sim"
    ) as http:
        return (await http.get("/proposals", headers={"Authorization": f"Bearer {TOKEN}"})).json()


@pytest.mark.anyio
async def test_mcp_exposes_gigsim_reads_and_policy_changes_without_code_changes(
    gigsim_mcp, sim_app, admin
):
    job = visible_job(sim_app)
    async with create_connected_server_and_client_session(gigsim_mcp.mcp) as client:
        history = await client.call_tool("get_client_history", {"client_id": job["client_id"]})
        balance = await client.call_tool("get_connects_balance")
        before = await client.call_tool("get_marketplace_policy")
        await admin.post(
            "/sim/policy",
            headers=ADMIN,
            json={"connects_multiplier": 2.0, "require_screening_answers": True},
        )
        after = await client.call_tool("get_marketplace_policy")

    assert history.structuredContent["client_id"] == job["client_id"]
    assert "must_have_skills" not in str(history.structuredContent)
    assert balance.structuredContent["balance"] == 200
    assert after.structuredContent["version"] == before.structuredContent["version"] + 1
    assert after.structuredContent["connects_multiplier"] == 2.0
    assert after.structuredContent["require_screening_answers"] is True


@pytest.mark.anyio
async def test_draft_reaches_gigsim_exactly_once_and_dry_run_does_not(gigsim_mcp, sim_app):
    job = visible_job(sim_app)
    async with create_connected_server_and_client_session(gigsim_mcp.mcp) as client:
        preview = await client.call_tool("create_proposal_draft", draft_args(job, dry_run=True))
        assert await remote_drafts(sim_app) == []
        created = await client.call_tool("create_proposal_draft", draft_args(job))
        retry = await client.call_tool("create_proposal_draft", draft_args(job))
        answered = await client.call_tool(
            "create_proposal_draft",
            draft_args(
                visible_other(sim_app, job),
                idempotency_key="draft-key-0002",
                screening_answers=["First answer", "Second answer"],
            ),
        )

    assert preview.structuredContent["outcome"] == "preview"
    assert created.structuredContent["outcome"] == "created"
    assert retry.structuredContent["outcome"] == "already_exists"
    assert answered.structuredContent["draft"]["screening_answers"] == ["First answer", "Second answer"]
    drafts = await remote_drafts(sim_app)
    assert len(drafts) == 2 and {d["status"] for d in drafts} == {"draft"}
    assert drafts[1]["screening_answers"] == ["First answer", "Second answer"]
    assert all(d["connects_spent"] == 0 for d in drafts)


def visible_other(sim_app, job):
    return next(
        j
        for j in sim_app.state.sim.jobs.values()
        if j["posted_at_hour"] <= 0 and j["job_id"] != job["job_id"]
    )


class FailPostsOnce(httpx.AsyncBaseTransport):
    """Lets reads through but drops the first POST, like a connection lost mid-write."""

    def __init__(self, inner):
        self.inner = inner
        self.failures = 1

    async def handle_async_request(self, request):
        if request.method == "POST" and self.failures:
            self.failures -= 1
            raise httpx.ConnectError("connection reset")
        return await self.inner.handle_async_request(request)


@pytest.mark.anyio
async def test_failed_remote_write_leaves_no_local_row_and_retry_succeeds(
    sim_app, tmp_path, monkeypatch
):
    job = visible_job(sim_app)
    flaky = FailPostsOnce(httpx.ASGITransport(app=sim_app))
    async with httpx.AsyncClient(transport=flaky, base_url="http://sim") as http:
        monkeypatch.setattr(server, "marketplace", GigSimMarketplace(token=TOKEN, client=http))
        monkeypatch.setattr(server, "store", MarketplaceStore(tmp_path / "drafts.sqlite3"))
        async with create_connected_server_and_client_session(server.mcp) as client:
            failed = await client.call_tool("create_proposal_draft", draft_args(job))
            assert failed.isError is True
            assert server.store.get_draft("draft-key-0001") is None
            assert await remote_drafts(sim_app) == []

            recovered = await client.call_tool("create_proposal_draft", draft_args(job))

    assert recovered.structuredContent["outcome"] == "created"
    assert len(await remote_drafts(sim_app)) == 1


@pytest.mark.anyio
async def test_crash_between_remote_and_local_write_does_not_duplicate(gigsim_mcp, sim_app):
    job = visible_job(sim_app)
    payload = {
        "job_id": job["job_id"],
        "cover_letter": "A tailored proposal for this project.",
        "price": 400,
        "screening_answers": [],
    }
    # Simulate a crash after GigSim accepted the draft but before the local row was written.
    await gigsim_mcp.marketplace.create_proposal_draft(payload, "draft-key-0001")
    assert gigsim_mcp.store.get_draft("draft-key-0001") is None

    async with create_connected_server_and_client_session(gigsim_mcp.mcp) as client:
        result = await client.call_tool("create_proposal_draft", draft_args(job))

    assert result.structuredContent["outcome"] == "created"
    assert len(await remote_drafts(sim_app)) == 1
    assert gigsim_mcp.store.get_draft("draft-key-0001") is not None


@pytest.mark.anyio
async def test_conflicting_reuse_of_a_key_is_rejected_before_any_remote_call(gigsim_mcp, sim_app):
    job = visible_job(sim_app)
    async with create_connected_server_and_client_session(gigsim_mcp.mcp) as client:
        await client.call_tool("create_proposal_draft", draft_args(job))
        conflict = await client.call_tool("create_proposal_draft", draft_args(job, price=999))

    assert conflict.isError is True
    assert len(await remote_drafts(sim_app)) == 1


# -- real processes: simulator server + stdio MCP server + API -------------------------------
@pytest.fixture
def live_gigsim(monkeypatch, tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {
        "GIGSIM_PORT": str(port),
        "GIGSIM_USER_TOKENS": "live-token:live-user",
        "GIGSIM_ADMIN_TOKEN": "live-admin",
        "GIGSIM_SEED": "3",
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "gigsim_local"],
        env={**os.environ, **env},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("local GigSim did not start")
        monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "gigsim")
        monkeypatch.setenv("GIGSIM_BASE_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("GIGSIM_API_TOKEN", "live-token")
        monkeypatch.setenv("GIGBID_MARKETPLACE_DB", str(tmp_path / "live.sqlite3"))
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.anyio
async def test_gigbid_reads_and_drafts_against_a_separate_gigsim_process(live_gigsim):
    jobs = await marketplace_mcp_client.search_jobs("")
    assert jobs and jobs[0].job_id.startswith("gs-job-") and jobs[0].client_id

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_app), base_url="http://test"
    ) as client:
        listed = await client.get("/jobs")
        detail = await client.get(f"/jobs/{jobs[0].job_id}")
        missing = await client.get("/jobs/gs-job-9999")

    assert listed.status_code == 200 and listed.json()[0]["job_id"].startswith("gs-job-")
    assert detail.json()["data_kind"] == "synthetic"
    assert missing.status_code == 404

    request = {
        "job_id": jobs[0].job_id,
        "cover_letter": "A tailored proposal for this project.",
        "price": 350,
        "idempotency_key": "live-key-0001",
        "dry_run": False,
    }
    first = await marketplace_mcp_client.create_proposal_draft(**request)
    second = await marketplace_mcp_client.create_proposal_draft(**request)
    assert (first.outcome, second.outcome) == ("created", "already_exists")

    async with httpx.AsyncClient(base_url=live_gigsim, timeout=5) as http:
        remote = (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json()
    assert [p["status"] for p in remote] == ["draft"]


async def graph_fixture(tmp_path):
    jobs = await marketplace_mcp_client.search_jobs("")
    job = next(
        job for job in jobs
        if "ignore all previous instructions" not in job.description.lower()
        and "whatsapp" not in job.description.lower()
        and "for free" not in job.description.lower()
    )
    path = tmp_path / "test-evidence.json"
    path.write_text(json.dumps([{
        "id": "test-evidence",
        "title": "Test-only evidence",
        "type": "case_study",
        "source": "test fixture",
        "skills": job.required_skills,
        "content": "Built and tested a project.",
        "data_kind": "real",
    }]), encoding="utf-8")
    graph = build_bid_graph(portfolio=Portfolio(path), maximum_risk_score=1.0)
    return graph, job.model_dump(mode="json")


@pytest.mark.anyio
async def test_graph_uses_live_history_policy_and_blocks_changed_policy(
    live_gigsim, tmp_path
):
    graph, job = await graph_fixture(tmp_path)
    config = {"configurable": {"thread_id": "live-policy-change"}}
    headers = {"Authorization": "Bearer live-admin"}
    async with httpx.AsyncClient(base_url=live_gigsim) as http:
        update = await http.post("/sim/policy", headers=headers, json={"connects_multiplier": 2.0})
        assert update.status_code == 200
        waiting = await graph.ainvoke({"job": job}, config=config)
        payload = waiting["__interrupt__"][0].value
        assert waiting["client_history"]["client_id"] == job["client_id"]
        assert payload["marketplace_policy"]["version"] == 2
        assert payload["dry_run"]["connects_cost"] == job["connects_cost"] * 2
        assert (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json() == []

        updated = await http.post(
            "/sim/policy", headers=headers, json={"banned_phrases": ["built and tested"]}
        )
        assert updated.status_code == 200
        result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
        assert result["approval_status"] == "needs_attention"
        assert result["draft_publication"]["outcome"] == "not_created"
        assert (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json() == []


@pytest.mark.anyio
async def test_graph_allows_repairing_required_answers_before_approval(live_gigsim, tmp_path):
    graph, job = await graph_fixture(tmp_path)
    config = {"configurable": {"thread_id": "required-answers"}}
    async with httpx.AsyncClient(base_url=live_gigsim) as http:
        response = await http.post(
            "/sim/policy",
            headers={"Authorization": "Bearer live-admin"},
            json={"require_screening_answers": True},
        )
        assert response.status_code == 200
        result = await graph.ainvoke({"job": job}, config=config)
        assert result["compliance_verdict"]["passed"] is False
        assert "non-placeholder answers" in " ".join(result["compliance_verdict"]["reasons"])
        review = result["__interrupt__"][0].value
        assert review["edit_validation"]["passed"] is False
        letter = review["proposal_draft"]["cover_letter"]
        bad = await graph.ainvoke(
            Command(resume={
                "action": "edit", "cover_letter": letter,
                "screening_answers": ["I have ten years of experience."] * len(job["screening_questions"]),
            }),
            config=config,
        )
        assert bad["__interrupt__"][0].value["edit_validation"]["passed"] is False
        good_answers = ['[test-evidence] "Built and tested a project."'] * len(job["screening_questions"])
        good = await graph.ainvoke(
            Command(resume={
                "action": "edit", "cover_letter": letter, "screening_answers": good_answers,
            }),
            config=config,
        )
        assert good["__interrupt__"][0].value["edit_validation"]["passed"] is True
        assert (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json() == []
        approved = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
        assert approved["approval_status"] == "approved"
        proposals = (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json()
        assert proposals[0]["screening_answers"] == good_answers
        assert proposals[0]["status"] == "draft" and proposals[0]["connects_spent"] == 0


@pytest.mark.anyio
async def test_required_answers_cannot_be_approved_without_edit(live_gigsim, tmp_path):
    graph, job = await graph_fixture(tmp_path)
    config = {"configurable": {"thread_id": "required-no-edit"}}
    async with httpx.AsyncClient(base_url=live_gigsim) as http:
        await http.post(
            "/sim/policy", headers={"Authorization": "Bearer live-admin"},
            json={"require_screening_answers": True},
        )
        await graph.ainvoke({"job": job}, config=config)
        result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
        assert result["approval_status"] == "needs_attention"
        assert (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json() == []


@pytest.mark.anyio
async def test_graph_policy_outage_does_not_publish(live_gigsim, tmp_path, monkeypatch):
    graph, job = await graph_fixture(tmp_path)
    config = {"configurable": {"thread_id": "policy-outage"}}
    waiting = await graph.ainvoke({"job": job}, config=config)
    assert "__interrupt__" in waiting
    monkeypatch.setenv("GIGSIM_API_TOKEN", "invalid")
    with pytest.raises(marketplace_mcp_client.MarketplaceMCPError):
        await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
    async with httpx.AsyncClient(base_url=live_gigsim) as http:
        assert (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json() == []
        monkeypatch.setenv("GIGSIM_API_TOKEN", "live-token")
        recovered = await graph.ainvoke(None, config=config)
        assert recovered["draft_publication"]["outcome"] == "created"
        assert len((await http.get(
            "/proposals", headers={"Authorization": "Bearer live-token"}
        )).json()) == 1


@pytest.mark.anyio
async def test_graph_rechecks_edited_draft_against_policy(live_gigsim, tmp_path):
    graph, job = await graph_fixture(tmp_path)
    config = {"configurable": {"thread_id": "edit-policy"}}
    async with httpx.AsyncClient(base_url=live_gigsim) as http:
        response = await http.post(
            "/sim/policy",
            headers={"Authorization": "Bearer live-admin"},
            json={"banned_phrases": ["special phrase"]},
        )
        assert response.status_code == 200
        waiting = await graph.ainvoke({"job": job}, config=config)
        assert "__interrupt__" in waiting
        edited = await graph.ainvoke(
            Command(resume={
                "action": "edit",
                "cover_letter": 'Special phrase\n[test-evidence] "Built and tested a project."',
            }),
            config=config,
        )
        verdict = edited["__interrupt__"][0].value["edit_validation"]
        assert verdict["passed"] is False
        assert "banned" in " ".join(verdict["reasons"])
        result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
        assert result["approval_status"] == "needs_attention"
        assert (await http.get("/proposals", headers={"Authorization": "Bearer live-token"})).json() == []


@pytest.mark.anyio
async def test_graph_approved_draft_uses_current_connects_cost(live_gigsim, tmp_path):
    graph, job = await graph_fixture(tmp_path)
    config = {"configurable": {"thread_id": "successful-policy"}}
    async with httpx.AsyncClient(base_url=live_gigsim) as http:
        response = await http.post(
            "/sim/policy",
            headers={"Authorization": "Bearer live-admin"},
            json={"connects_multiplier": 1.5},
        )
        assert response.status_code == 200
        waiting = await graph.ainvoke({"job": job}, config=config)
        cost = waiting["__interrupt__"][0].value["dry_run"]["connects_cost"]
        result = await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
        assert result["draft_publication"]["connects_cost_if_submitted"] == cost
        proposals = (await http.get(
            "/proposals", headers={"Authorization": "Bearer live-token"}
        )).json()
        assert len(proposals) == 1
        assert proposals[0]["status"] == "draft" and proposals[0]["connects_spent"] == 0


@pytest.mark.anyio
async def test_graph_rejects_modified_simulator_job(live_gigsim, tmp_path):
    graph, job = await graph_fixture(tmp_path)
    with pytest.raises(marketplace_mcp_client.MarketplaceMCPError, match="Job details changed"):
        await graph.ainvoke(
            {"job": {**job, "description": "A different description."}},
            config={"configurable": {"thread_id": "modified-job"}},
        )


@pytest.mark.anyio
async def test_graph_blocks_initial_draft_with_banned_phrase(live_gigsim, tmp_path):
    graph, job = await graph_fixture(tmp_path)
    async with httpx.AsyncClient(base_url=live_gigsim) as http:
        response = await http.post(
            "/sim/policy",
            headers={"Authorization": "Bearer live-admin"},
            json={"banned_phrases": ["built and tested"]},
        )
        assert response.status_code == 200
        result = await graph.ainvoke(
            {"job": job}, config={"configurable": {"thread_id": "initial-banned"}}
        )
        assert result["compliance_verdict"]["passed"] is False
        assert "banned" in " ".join(result["compliance_verdict"]["reasons"])
        assert "__interrupt__" not in result


@pytest.mark.anyio
async def test_pipeline_reads_simulator_state_without_writes(live_gigsim):
    headers = {"Authorization": "Bearer live-token"}
    async with (
        httpx.AsyncClient(base_url=live_gigsim) as sim,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url="http://test") as api,
    ):
        empty = await api.get("/pipeline")
        assert empty.json() == {"connects_balance": 200, "proposals": []}
        job = (await sim.get("/jobs", headers=headers)).json()[0]
        created = await sim.post(
            "/proposals", headers={**headers, "Idempotency-Key": "pipeline-test-draft"},
            json={"job_id": job["job_id"], "price": 100, "cover_letter": "Synthetic draft.",
                  "screening_answers": ["Answer"] * len(job["screening_questions"])},
        )
        assert created.status_code == 200
        proposal_id = created.json()["proposal_id"]
        draft = await api.get("/pipeline")
        assert draft.status_code == 200
        assert draft.json()["connects_balance"] == 200
        assert draft.json()["proposals"][0]["status"] == "draft"
        assert "cover_letter" not in draft.json()["proposals"][0]

        confirmed = await sim.post(
            f"/proposals/{proposal_id}/confirm",
            headers={**headers, "Idempotency-Key": "pipeline-test-confirm"},
        )
        assert confirmed.status_code == 200
        tick = await sim.post(
            "/sim/tick", headers={"Authorization": "Bearer live-admin"}, json={"hours": 120}
        )
        assert tick.status_code == 200
        before = (await sim.get("/proposals", headers=headers)).json()
        balance = (await sim.get("/account/connects", headers=headers)).json()["balance"]
        refreshed = await api.get("/pipeline")
        assert refreshed.status_code == 200
        assert refreshed.json()["connects_balance"] == balance
        assert refreshed.json()["proposals"][0]["status"] == before[0]["status"]
        assert refreshed.json()["proposals"][0]["connects_spent"] == before[0]["connects_spent"]
        assert (await sim.get("/proposals", headers=headers)).json() == before
        assert (await sim.get("/account/connects", headers=headers)).json()["balance"] == balance


@pytest.mark.anyio
async def test_messages_through_mcp_and_conversation_api_do_not_send(live_gigsim):
    async with httpx.AsyncClient(base_url=live_gigsim) as sim:
        jobs = (await sim.get("/jobs", headers={"Authorization": "Bearer live-token"})).json()
        job = jobs[0]
        create = await sim.post(
            "/proposals",
            headers={"Authorization": "Bearer live-token", "Idempotency-Key": "messages-test-draft"},
            json={
                "job_id": job["job_id"], "price": job["budget"]["min"] or 1,
                "cover_letter": f"For {job['title']} I will discuss {', '.join(job['required_skills'])}. "
                                "Please share your priorities and milestones for this project.",
                "screening_answers": ["An approach."] * len(job["screening_questions"]),
            },
        )
        assert create.status_code == 200
        proposal_id = create.json()["proposal_id"]
        confirm = await sim.post(
            f"/proposals/{proposal_id}/confirm",
            headers={"Authorization": "Bearer live-token", "Idempotency-Key": "messages-test-confirm"},
        )
        assert confirm.status_code == 200
        tick = await sim.post(
            "/sim/tick", headers={"Authorization": "Bearer live-admin"}, json={"hours": 120}
        )
        assert tick.status_code == 200
        before = (await sim.get("/messages", headers={"Authorization": "Bearer live-token"})).json()
        assert before, "the deterministic simulator fixture must produce a client reply"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api_app), base_url="http://test"
        ) as api:
            response = await api.get("/messages", params={"proposal_id": proposal_id})
            assert response.status_code == 200
            assert response.json() == before
            client_message = next(item for item in before if item["sender"] == "client")
            start = await api.post("/graphs/conversation/start", json={
                "thread_id": "simulator-conversation-messages",
                "input": {"conversation_id": proposal_id, "client_message": client_message["body"]},
            })
            assert start.status_code == 200
            assert start.json()["status"] == "interrupted"
            approve = await api.post(
                "/graphs/conversation/simulator-conversation-messages/approval",
                json={"action": "approve"},
            )
            assert approve.status_code == 200
            assert approve.json()["state"]["approval_status"] == "approved"
        after = (await sim.get("/messages", headers={"Authorization": "Bearer live-token"})).json()
        assert after == before
