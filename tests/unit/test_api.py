import httpx
import pytest

from apps.api.main import app


@pytest.mark.anyio
async def test_health_endpoint():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_job_api_lists_and_filters_synthetic_sample_jobs():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        all_jobs = await client.get("/jobs")
        filtered_jobs = await client.get("/jobs", params={"query": "churn prediction"})

    assert all_jobs.status_code == 200
    assert len(all_jobs.json()) == 2
    assert all(job["data_kind"] == "synthetic" for job in all_jobs.json())
    assert filtered_jobs.status_code == 200
    assert [job["job_id"] for job in filtered_jobs.json()] == ["sample-job-001"]


@pytest.mark.anyio
async def test_job_api_returns_detail_and_not_found_status():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        found = await client.get("/jobs/sample-job-001")
        missing = await client.get("/jobs/unknown-job")
        invalid = await client.get("/jobs/" + "x" * 201)

    assert found.status_code == 200
    assert found.json()["title"] == "Build a customer churn prediction baseline"
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_job_api_openapi_documents_unavailable_and_not_found():
    paths = app.openapi()["paths"]
    assert "503" in paths["/jobs"]["get"]["responses"]
    assert {"404", "503"} <= set(paths["/jobs/{job_id}"]["get"]["responses"])


@pytest.mark.anyio
async def test_graph_api_starts_and_resumes_conversation_for_approval():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        start = await client.post(
            "/graphs/conversation/start",
            json={
                "thread_id": "api-conversation-1",
                "input": {
                    "conversation_id": "conversation-1",
                    "client_message": "Can we schedule an interview?",
                    "available_slots": ["2026-11-12 10:00 PKT"],
                },
            },
        )

        assert start.status_code == 200
        start_result = start.json()
        assert start_result["status"] == "interrupted"
        assert (
            start_result["interrupts"][0]["draft"]["intent"] == "interview_request"
        )

        restored = await client.get("/graphs/conversation/api-conversation-1")
        assert restored.status_code == 200
        assert restored.json()["status"] == "interrupted"
        assert restored.json()["interrupts"] == start_result["interrupts"]
        approval = await client.post(
            "/graphs/conversation/api-conversation-1/approval",
            json={"action": "approve"},
        )
        finished = await client.get("/graphs/conversation/api-conversation-1")
        repeated = await client.post(
            "/graphs/conversation/api-conversation-1/approval", json={"action": "approve"}
        )

    assert approval.status_code == 200
    assert approval.json()["state"]["approval_status"] == "approved"
    assert finished.json()["status"] == "completed"
    assert finished.json()["state"]["approval_status"] == "approved"
    assert repeated.status_code == 409


@pytest.mark.anyio
async def test_graph_lookup_and_approval_reject_unknown_threads():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        missing = await client.get("/graphs/bid/missing-thread")
        approval = await client.post(
            "/graphs/bid/missing-thread/approval", json={"action": "approve"}
        )
    assert missing.status_code == 404
    assert approval.status_code == 404


@pytest.mark.anyio
async def test_graph_api_uses_synthetic_sample_and_does_not_interrupt_to_bid():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/graphs/bid/start",
            json={
                "thread_id": "api-sample-job",
                "input": {
                    "job": {
                        "job_id": "sample-job-001",
                        "title": "Build a churn classifier",
                        "description": "Use Python and scikit-learn.",
                        "required_skills": ["Python", "scikit-learn"],
                        "budget": {"min": 250, "max": 450, "currency": "USD"},
                        "warning_signals": [],
                    }
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["state"]["decision"] == "watch"
    assert response.json()["status"] == "completed"


@pytest.mark.anyio
async def test_graph_stream_emits_progress_and_approval_interrupt():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/graphs/conversation/stream",
            json={
                "thread_id": "stream-conversation-1",
                "input": {
                    "conversation_id": "conversation-1",
                    "client_message": "Can you clarify this?",
                },
            },
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: update" in response.text
    assert "client_liaison" in response.text
    assert "__interrupt__" in response.text
    assert 'event: complete\ndata: {"status": "interrupted"}' in response.text


@pytest.mark.anyio
async def test_graph_approval_rejects_invalid_edit_fields():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        url = "/graphs/conversation/api-conversation-edit/approval"
        for payload in [
            {"action": "edit", "cover_letter": "Edited reply"},
            {"action": "edit", "message": "  "},
            {"action": "edit", "message": "x" * 5001},
            {"action": "edit", "message": "Reply", "screening_answers": []},
            {"action": "approve", "message": "Reply"},
        ]:
            assert (await client.post(url, json=payload)).status_code == 422
        assert (await client.post(
            "/graphs/bid/api-bid-edit/approval", json={"action": "edit", "message": "Reply"}
        )).status_code == 422
