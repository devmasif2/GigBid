import httpx
import pytest

from gigsim_local.app import create_app
from gigsim_local.data import generate_world
from gigsim_local.engine import SimConfig
from gigsim_local.reply_model import decide

USER = {"Authorization": "Bearer tok-a"}
OTHER = {"Authorization": "Bearer tok-b"}
ADMIN = {"Authorization": "Bearer admin-secret"}


def make_config(**overrides):
    values = {
        "seed": 7,
        "job_count": 40,
        "client_count": 10,
        "user_tokens": {"tok-a": "user-a", "tok-b": "user-b"},
        "admin_token": "admin-secret",
        "rate_limit_per_minute": 1000,
        "initial_connects": 100,
    }
    return SimConfig(**{**values, **overrides})


@pytest.fixture
def app():
    return create_app(make_config())


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sim"
    ) as http:
        yield http


def visible_job(app):
    sim = app.state.sim
    return next(job for job in sim.jobs.values() if job["posted_at_hour"] <= 0)


def strong_letter(app, job):
    sim = app.state.sim
    hidden = sim.clients[job["client_id"]]["hidden"]
    skills = ", ".join(hidden["must_have_skills"])
    return (
        f"For '{job['title']}' I would use {skills}. In two earlier projects I delivered 3 "
        "milestones in 14 days with 95 percent test coverage, and I can start on day 1."
    )


def good_price(app, job):
    return app.state.sim.clients[job["client_id"]]["hidden"]["budget_ceiling"] * 0.8


def proposal_body(app, job, letter=None, price=None, answers=True):
    return {
        "job_id": job["job_id"],
        "cover_letter": letter or strong_letter(app, job),
        "price": price or good_price(app, job),
        "screening_answers": ["answer"] * len(job["screening_questions"]) if answers else [],
    }


def idem(key="idem-key-0001"):
    return {**USER, "Idempotency-Key": key}


# -- data ------------------------------------------------------------------------------------
def test_world_is_deterministic_and_seed_dependent():
    first = generate_world(5, 30, 8)
    again = generate_world(5, 30, 8)
    other = generate_world(6, 30, 8)

    assert first == again
    assert first["jobs"] != other["jobs"]
    assert any(t["is_scam"] for t in generate_world(5, 400, 20)["truth"].values())


@pytest.mark.anyio
async def test_invalid_policy_update_is_atomic(client):
    before = (await client.get("/policy", headers=USER)).json()
    response = await client.post(
        "/sim/policy",
        headers=ADMIN,
        json={"connects_multiplier": 2.0, "banned_phrases": [""]},
    )
    assert response.status_code == 422
    assert (await client.get("/policy", headers=USER)).json() == before


@pytest.mark.anyio
async def test_hidden_ground_truth_is_not_exposed_to_agents(client, app):
    job = visible_job(app)
    listed = (await client.get("/jobs", headers=USER)).json()
    detail = (await client.get(f"/jobs/{job['job_id']}", headers=USER)).json()
    history = (await client.get(f"/clients/{job['client_id']}/history", headers=USER)).json()

    blob = str(listed) + str(detail) + str(history)
    for hidden_field in ("must_have_skills", "budget_ceiling", "reply_threshold", "is_scam"):
        assert hidden_field not in blob
    assert detail["data_kind"] == "synthetic"
    assert (await client.get("/sim/ground-truth", headers=USER)).status_code == 403
    truth = (await client.get("/sim/ground-truth", headers=ADMIN)).json()
    assert job["job_id"] in truth["jobs"]


# -- auth, rate limit, faults ----------------------------------------------------------------
@pytest.mark.anyio
async def test_authentication_is_required_and_admin_is_separate(client):
    assert (await client.get("/jobs")).status_code == 401
    assert (await client.get("/jobs", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await client.get("/jobs", headers=USER)).status_code == 200
    assert (await client.post("/sim/tick", headers=USER, json={"hours": 1})).status_code == 403
    assert (await client.post("/sim/tick", headers=ADMIN, json={"hours": 1})).status_code == 200
    assert (await client.get("/health")).status_code == 200


@pytest.mark.anyio
async def test_rate_limit_returns_429_with_retry_after_then_recovers():
    now = [1000.0]
    app = create_app(make_config(rate_limit_per_minute=3), time_fn=lambda: now[0])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sim"
    ) as http:
        statuses = [(await http.get("/jobs", headers=USER)).status_code for _ in range(3)]
        limited = await http.get("/jobs", headers=USER)
        other_user = await http.get("/jobs", headers=OTHER)
        health = await http.get("/health")
        now[0] += 61
        recovered = await http.get("/jobs", headers=USER)

    assert statuses == [200, 200, 200]
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    assert other_user.status_code == 200
    assert health.status_code == 200
    assert recovered.status_code == 200


@pytest.mark.anyio
async def test_fault_injection_produces_503_then_recovers(client):
    await client.post("/sim/faults", headers=ADMIN, json={"fail_next": 2})
    codes = [(await client.get("/jobs", headers=USER)).status_code for _ in range(3)]
    assert codes == [503, 503, 200]

    await client.post("/sim/faults", headers=ADMIN, json={"error_rate": 1.0})
    failing = await client.get("/jobs", headers=USER)
    assert failing.status_code == 503
    assert failing.headers["Retry-After"] == "1"
    assert (await client.get("/health")).status_code == 200


# -- jobs ------------------------------------------------------------------------------------
@pytest.mark.anyio
async def test_job_search_pagination_and_unknown_job(client, app):
    jobs = (await client.get("/jobs", headers=USER, params={"limit": 5})).json()
    assert len(jobs) == 5
    assert jobs == sorted(jobs, key=lambda j: (-j["posted_at_hour"], j["job_id"]))
    skill = jobs[0]["required_skills"][0]
    hits = (await client.get("/jobs", headers=USER, params={"query": skill, "limit": 100})).json()
    assert hits and all(skill.casefold() in str(j).casefold() for j in hits)
    page2 = (await client.get("/jobs", headers=USER, params={"limit": 5, "offset": 5})).json()
    assert {j["job_id"] for j in page2}.isdisjoint({j["job_id"] for j in jobs})
    assert (await client.get("/jobs/does-not-exist", headers=USER)).status_code == 404
    assert (await client.get("/jobs", headers=USER, params={"limit": 0})).status_code == 422


@pytest.mark.anyio
async def test_future_jobs_appear_when_the_clock_advances(client, app):
    future = next(j for j in app.state.sim.jobs.values() if j["posted_at_hour"] > 0)
    assert (await client.get(f"/jobs/{future['job_id']}", headers=USER)).status_code == 404
    await client.post("/sim/tick", headers=ADMIN, json={"hours": future["posted_at_hour"]})
    assert (await client.get(f"/jobs/{future['job_id']}", headers=USER)).status_code == 200
    fresh = await client.get("/jobs", headers=USER, params={"since_hour": 0, "limit": 100})
    assert future["job_id"] in {j["job_id"] for j in fresh.json()}


# -- proposals -------------------------------------------------------------------------------
@pytest.mark.anyio
async def test_draft_creation_is_idempotent_and_validated(client, app):
    job = visible_job(app)
    body = proposal_body(app, job)

    first = await client.post("/proposals", headers=idem(), json=body)
    replay = await client.post("/proposals", headers=idem(), json=body)
    conflict = await client.post("/proposals", headers=idem(), json={**body, "price": 1.0})
    no_key = await client.post("/proposals", headers=USER, json=body)
    bad_price = await client.post("/proposals", headers=idem("idem-key-0002"), json={**body, "price": 0})
    unknown = await client.post(
        "/proposals", headers=idem("idem-key-0003"), json={**body, "job_id": "missing"}
    )
    same_job_again = await client.post("/proposals", headers=idem("idem-key-0004"), json=body)

    assert first.status_code == 200 and first.json()["status"] == "draft"
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert no_key.status_code == 422
    assert bad_price.status_code == 422
    assert unknown.status_code == 404
    assert same_job_again.status_code == 409
    assert len((await client.get("/proposals", headers=USER)).json()) == 1
    assert (await client.get("/proposals", headers=OTHER)).json() == []


@pytest.mark.anyio
async def test_confirm_spends_connects_exactly_once(client, app):
    job = visible_job(app)
    draft = (await client.post("/proposals", headers=idem(), json=proposal_body(app, job))).json()
    path = f"/proposals/{draft['proposal_id']}/confirm"

    first = await client.post(path, headers=idem("confirm-key-1"))
    retry = await client.post(path, headers=idem("confirm-key-1"))
    other_key = await client.post(path, headers=idem("confirm-key-2"))
    balance = (await client.get("/account/connects", headers=USER)).json()["balance"]

    assert first.json()["status"] == "submitted"
    assert first.json()["connects_spent"] == job["connects_cost"]
    assert retry.headers["Idempotent-Replay"] == "true"
    assert other_key.status_code == 409
    assert balance == 100 - job["connects_cost"]
    assert (await client.get("/account/connects", headers=OTHER)).json()["balance"] == 100


@pytest.mark.anyio
async def test_insufficient_connects_is_rejected_without_spending(app):
    app = create_app(make_config(initial_connects=1))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sim"
    ) as http:
        job = visible_job(app)
        draft = (await http.post("/proposals", headers=idem(), json=proposal_body(app, job))).json()
        refused = await http.post(f"/proposals/{draft['proposal_id']}/confirm", headers=idem("c-key-0001"))
        balance = (await http.get("/account/connects", headers=USER)).json()["balance"]

    assert refused.status_code == 402
    assert balance == 1


@pytest.mark.anyio
async def test_strong_proposal_progresses_through_events_and_messages(client, app):
    job = visible_job(app)
    draft = (await client.post("/proposals", headers=idem(), json=proposal_body(app, job))).json()
    pid = draft["proposal_id"]
    await client.post(f"/proposals/{pid}/confirm", headers=idem("confirm-key-1"))

    assert (await client.get(f"/proposals/{pid}", headers=USER)).json()["status"] == "submitted"
    await client.post("/sim/tick", headers=ADMIN, json={"hours": 120})

    final = (await client.get(f"/proposals/{pid}", headers=USER)).json()
    events = (await client.get("/events", headers=USER)).json()
    messages = (await client.get("/messages", headers=USER, params={"proposal_id": pid})).json()
    later = (await client.get("/events", headers=USER, params={"after_id": events[2]["event_id"]})).json()

    assert final["status"] == "hired"
    statuses = [e["status"] for e in events if e["type"] == "proposal_status"]
    assert statuses == ["submitted", "viewed", "replied", "interview", "hired"]
    assert [m["sender"] for m in messages] == ["client"] * 3
    assert len(later) == len(events) - 3
    assert (await client.get("/events", headers=OTHER)).json() == []


@pytest.mark.anyio
async def test_weak_generic_proposal_is_ignored(client, app):
    job = visible_job(app)
    body = proposal_body(
        app, job, letter="Dear sir, I am writing to apply.", price=10_000_000 / 100, answers=False
    )
    draft = (await client.post("/proposals", headers=idem(), json=body)).json()
    pid = draft["proposal_id"]
    await client.post(f"/proposals/{pid}/confirm", headers=idem("confirm-key-1"))
    await client.post("/sim/tick", headers=ADMIN, json={"hours": 120})

    assert (await client.get(f"/proposals/{pid}", headers=USER)).json()["status"] == "lost"
    assert (await client.get("/messages", headers=USER)).json() == []
    outcomes = (await client.get("/sim/outcomes", headers=ADMIN)).json()
    assert outcomes["submitted"] == 1 and outcomes["reply_rate"] == 0.0


@pytest.mark.anyio
async def test_messages_require_an_open_conversation_and_get_replies(client, app):
    job = visible_job(app)
    pid = (await client.post("/proposals", headers=idem(), json=proposal_body(app, job))).json()[
        "proposal_id"
    ]
    early = await client.post(
        "/messages", headers=idem("msg-key-001"), json={"proposal_id": pid, "body": "Hello"}
    )
    await client.post(f"/proposals/{pid}/confirm", headers=idem("confirm-key-1"))
    await client.post("/sim/tick", headers=ADMIN, json={"hours": 120})

    sent = await client.post(
        "/messages",
        headers=idem("msg-key-002"),
        json={"proposal_id": pid, "body": "I am free Monday at 10:00 or 3 pm."},
    )
    replay = await client.post(
        "/messages",
        headers=idem("msg-key-002"),
        json={"proposal_id": pid, "body": "I am free Monday at 10:00 or 3 pm."},
    )
    vague = await client.post(
        "/messages",
        headers=idem("msg-key-003"),
        json={"proposal_id": pid, "body": "Whenever suits you."},
    )
    await client.post("/sim/tick", headers=ADMIN, json={"hours": 3})
    messages = (await client.get("/messages", headers=USER, params={"proposal_id": pid})).json()

    assert early.status_code == 409
    assert sent.status_code == 200 and replay.headers["Idempotent-Replay"] == "true"
    assert vague.status_code == 200
    client_replies = [m["body"] for m in messages if m["sender"] == "client"][-2:]
    assert any("works" in text for text in client_replies)
    assert any("specific time slots" in text for text in client_replies)
    assert sum(m["body"].startswith("I am free") for m in messages) == 1


@pytest.mark.anyio
async def test_scam_clients_push_off_platform_and_inject_instructions():
    app = create_app(make_config(job_count=400, client_count=30))
    sim = app.state.sim
    scam_job = next(
        job
        for job_id, job in sim.jobs.items()
        if sim.truth[job_id]["scam_kinds"] == ["prompt_injection"] and job["posted_at_hour"] <= 0
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://sim"
    ) as http:
        pid = (
            await http.post("/proposals", headers=idem(), json=proposal_body(app, scam_job))
        ).json()["proposal_id"]
        await http.post(f"/proposals/{pid}/confirm", headers=idem("confirm-key-1"))
        await http.post("/sim/tick", headers=ADMIN, json={"hours": 150})
        messages = (await http.get("/messages", headers=USER)).json()

    # A strong proposal is hired, so the scam client's messages must exist and carry the attack.
    assert len(messages) == 3
    for message in messages:
        assert "WhatsApp" in message["body"]
        assert "Ignore previous instructions" in message["body"]


# -- policy change request -------------------------------------------------------------------
@pytest.mark.anyio
async def test_policy_update_changes_cost_and_rules_without_code_changes(client, app):
    job = visible_job(app)
    before = (await client.get("/policy", headers=USER)).json()
    updated = await client.post(
        "/sim/policy",
        headers=ADMIN,
        json={
            "connects_multiplier": 2.0,
            "require_screening_answers": True,
            "banned_phrases": ["synergy"],
        },
    )
    unanswered = (
        await client.post(
            "/proposals", headers=idem(), json=proposal_body(app, job, answers=False)
        )
    ).json()["proposal_id"]
    refused = await client.post(f"/proposals/{unanswered}/confirm", headers=idem("confirm-key-1"))
    banned = await client.post(
        "/proposals",
        headers=idem("idem-key-0009"),
        json=proposal_body(app, app.state.sim.jobs[next(
            j for j in app.state.sim.jobs if j != job["job_id"] and app.state.sim.jobs[j]["posted_at_hour"] <= 0
        )], letter="Great synergy " + strong_letter(app, job)),
    )
    banned_id = banned.json()["proposal_id"]
    banned_refused = await client.post(
        f"/proposals/{banned_id}/confirm", headers=idem("confirm-key-2")
    )

    assert updated.json()["version"] == before["version"] + 1
    assert (await client.get("/policy", headers=USER)).json()["connects_multiplier"] == 2.0
    assert refused.status_code == 422 and "screening" in refused.json()["detail"]
    assert banned_refused.status_code == 422 and "synergy" in banned_refused.json()["detail"]
    assert (await client.get("/account/connects", headers=USER)).json()["balance"] == 100


@pytest.mark.anyio
async def test_policy_multiplier_raises_connects_cost_and_bad_updates_are_rejected(client, app):
    job = visible_job(app)
    await client.post("/sim/policy", headers=ADMIN, json={"connects_multiplier": 1.5})
    pid = (await client.post("/proposals", headers=idem(), json=proposal_body(app, job))).json()[
        "proposal_id"
    ]
    confirmed = (await client.post(f"/proposals/{pid}/confirm", headers=idem("confirm-key-1"))).json()

    import math

    assert confirmed["connects_spent"] == math.ceil(job["connects_cost"] * 1.5)
    for bad in ({"connects_multiplier": 99}, {"unknown": 1}, {"banned_phrases": "x"},
                {"require_screening_answers": "yes"}):
        assert (await client.post("/sim/policy", headers=ADMIN, json=bad)).status_code == 422


@pytest.mark.anyio
async def test_reset_restores_the_initial_world(client, app):
    job = visible_job(app)
    await client.post("/proposals", headers=idem(), json=proposal_body(app, job))
    await client.post("/sim/tick", headers=ADMIN, json={"hours": 5})
    await client.post("/sim/reset", headers=ADMIN)

    assert (await client.get("/proposals", headers=USER)).json() == []
    assert (await client.get("/health")).json()["clock_hour"] == 0


# -- reply model -----------------------------------------------------------------------------
HIDDEN = {
    "must_have_skills": ["Python", "SQL"],
    "budget_ceiling": 1000.0,
    "dislikes_generic": True,
    "reply_threshold": 0.45,
}


def run_decide(letter, price=800.0, answers=1, hidden=HIDDEN, proposal_id="p-1"):
    return decide(
        seed=1,
        proposal_id=proposal_id,
        cover_letter=letter,
        price=price,
        answers=answers,
        questions=1,
        job_title="Build a Python reporting pipeline",
        hidden=hidden,
    )


def test_reply_model_rewards_specific_evidence_and_penalises_generic_or_unsafe_text():
    specific = (
        "For the Python reporting pipeline I would use Python and SQL; I built 2 similar "
        "pipelines processing 40 million rows each and can start immediately."
    )
    generic = "Dear sir, I am writing to apply. " + specific
    unsafe = specific + " Message me on WhatsApp and I guarantee results."

    good = run_decide(specific)
    assert good.score > run_decide(generic).score
    assert run_decide(unsafe).violations and run_decide(unsafe).score < good.score
    assert run_decide(specific, price=2000.0).score < good.score
    assert run_decide("Hi.").score < good.score
    assert good == run_decide(specific)
    assert run_decide(specific).outcome in {"replied", "interview", "hired"}
    assert run_decide(unsafe).outcome == "ignored"
