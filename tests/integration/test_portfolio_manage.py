import base64
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from agent.mcp_client import retrieve_portfolio_evidence
from apps.api.main import app
from rag.ingest.portfolio import SourceDocument
from rag.ingest.store import PortfolioStore, SourceConflict

TOKEN = "test-local-token-" * 3


@pytest.fixture
def configured(tmp_path, monkeypatch):
    database = tmp_path / "portfolio.sqlite3"
    monkeypatch.setenv("GIGBID_PORTFOLIO_PATH", str(database))
    monkeypatch.setenv("GIGBID_PORTFOLIO_MANAGE_TOKEN", TOKEN)
    return database


def upload_body(source_id="cv", content=b"Synthetic Python engineer.", **overrides):
    document = {
        "source_id": source_id, "path": "cv.txt", "freelancer_id": "demo", "title": "CV",
        "type": "cv", "skills": ["Python"], "data_kind": "synthetic",
    }
    document.update(overrides)
    return {"document": document, "content_base64": base64.b64encode(content).decode()}


@pytest.mark.anyio
async def test_manage_upload_replace_delete_and_mcp_search(configured):
    headers = {"x-portfolio-token": TOKEN}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post("/portfolio/manage/sources", json=upload_body(), headers=headers)
        assert created.status_code == 200, created.text
        first = created.json()["revision"]
        added = await client.post(
            "/portfolio/manage/sources", json=upload_body("case", title="Case"), headers=headers
        )
        assert added.status_code == 200
        sources = await client.get("/portfolio/manage/sources", headers=headers)
        assert {item["source_id"] for item in sources.json()} == {"cv", "case"}
        search = await retrieve_portfolio_evidence(["Python"], configured)
        assert len(search[0]) == 2
        assert all(item.data_kind == "synthetic" for item in search[0])

        updated = upload_body(content=b"Synthetic Python updated.")
        updated["expected_revision"] = first
        result = await client.post("/portfolio/manage/sources", json=updated, headers=headers)
        assert result.status_code == 200
        second = result.json()["revision"]
        assert second > first
        stale = await client.post("/portfolio/manage/sources", json=updated, headers=headers)
        assert stale.status_code == 409
        rows = (await retrieve_portfolio_evidence(["Python"], configured))[0]
        assert {row.content for row in rows} == {
            "Synthetic Python engineer.", "Synthetic Python updated."
        }
        delete = {"freelancer_id": "demo", "source_id": "cv", "expected_revision": second}
        assert (await client.post("/portfolio/manage/sources/delete", json=delete, headers=headers)).status_code == 200
        assert len((await retrieve_portfolio_evidence(["Python"], configured))[0]) == 1
        recreated = await client.post("/portfolio/manage/sources", json=upload_body(), headers=headers)
        assert recreated.json()["revision"] > second
        assert (await client.post("/portfolio/manage/sources/delete", json=delete, headers=headers)).status_code == 409
    assert configured.stat().st_mode & 0o077 == 0


@pytest.mark.anyio
async def test_disabled_wrong_token_remote_and_invalid_inputs(tmp_path, monkeypatch, configured):
    headers = {"x-portfolio-token": TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/portfolio/manage/sources")).status_code == 403
        assert not configured.exists()
        monkeypatch.delenv("GIGBID_PORTFOLIO_MANAGE_TOKEN")
        assert (await client.get("/portfolio/manage/sources", headers=headers)).status_code == 404
        monkeypatch.setenv("GIGBID_PORTFOLIO_MANAGE_TOKEN", TOKEN)
        invalid = upload_body(data_kind="real")
        assert (await client.post("/portfolio/manage/sources", json=invalid, headers=headers)).status_code == 422
        assert (await client.post("/portfolio/manage/sources", json=upload_body(path="../cv.txt"), headers=headers)).status_code == 422
        assert (await client.post("/portfolio/manage/sources", json=upload_body(content=b"\xff"), headers=headers)).status_code == 422
        bad = upload_body()
        bad["content_base64"] = "%%%%"
        assert (await client.post("/portfolio/manage/sources", json=bad, headers=headers)).status_code == 422
        too_big = await client.post("/portfolio/manage/sources", content=b"x" * 2_800_001, headers=headers)
        assert too_big.status_code == 413
    remote = httpx.ASGITransport(app=app, client=("203.0.113.1", 1234))
    async with httpx.AsyncClient(transport=remote, base_url="http://test") as client:
        assert (await client.get("/portfolio/manage/sources", headers=headers)).status_code == 403


@pytest.mark.anyio
async def test_invalid_update_does_not_replace_previous_evidence(configured):
    headers = {"x-portfolio-token": TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/portfolio/manage/sources", json=upload_body(), headers=headers)
        revision = response.json()["revision"]
        bad = upload_body(content=b"not pdf", path="cv.pdf")
        bad["expected_revision"] = revision
        assert (await client.post("/portfolio/manage/sources", json=bad, headers=headers)).status_code == 422
        source = (await client.get("/portfolio/manage/sources", headers=headers)).json()[0]
        assert source["revision"] == revision
        assert (await retrieve_portfolio_evidence(["Python"], configured))[0][0].content == "Synthetic Python engineer."


@pytest.mark.anyio
async def test_pdf_upload_and_explicit_real_attestation(configured, make_text_pdf):
    headers = {"x-portfolio-token": TOKEN}
    body = upload_body(
        content=make_text_pdf("Synthetic Python resume."), path="resume.pdf"
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/portfolio/manage/sources", json=body, headers=headers)
        assert response.status_code == 200
        evidence = (await retrieve_portfolio_evidence(["Python"], configured))[0][0]
        assert evidence.content == "Synthetic Python resume."
        assert evidence.data_kind == "synthetic"
        real = upload_body(source_id="real", data_kind="real", rights_attested=True)
        assert (await client.post("/portfolio/manage/sources", json=real, headers=headers)).status_code == 200
        assert {item.data_kind for item in (await retrieve_portfolio_evidence(["Python"], configured))[0]} == {
            "synthetic", "real"
        }


def test_concurrent_replacements_reject_stale_revision(configured):
    store = PortfolioStore(configured)
    store.initialize()
    document = SourceDocument.model_validate(upload_body()["document"])
    revision = store.put(document, b"Original Python", None)

    def update(text):
        try:
            return store.put(document, text, revision)
        except SourceConflict:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(update, [b"First Python", b"Second Python"]))
    assert sum(value is not None for value in outcomes) == 1
    reopened = PortfolioStore(configured)
    assert reopened.list_sources()[0]["revision"] in outcomes


def test_store_missing_database_does_not_create_on_read(tmp_path):
    import sqlite3

    from rag.ingest.store import read_store_items

    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        read_store_items(path)
    assert not path.exists()
