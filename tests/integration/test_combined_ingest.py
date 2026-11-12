import hashlib
import json
import subprocess
import sys

import anyio
import pytest
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents, Tool
from pydantic import ValidationError

from agent.mcp_client import retrieve_portfolio_evidence
from rag.ingest import combined
from rag.ingest.github import build_github_index
from rag.ingest.portfolio import write_index


@pytest.fixture
def manifests(tmp_path, make_text_pdf):
    (tmp_path / "cv.pdf").write_bytes(make_text_pdf("Synthetic Python CV."))
    (tmp_path / "case.md").write_text("Synthetic Python case study.")
    base = {
        "freelancer_id": "demo", "skills": ["Python"], "data_kind": "synthetic",
    }
    local = {
        "version": 1,
        "documents": [
            {**base, "source_id": "cv", "path": "cv.pdf", "title": "CV", "type": "cv"},
            {**base, "source_id": "case", "path": "case.md", "title": "Case", "type": "case_study"},
        ],
    }
    github = {
        "version": 1,
        "documents": [{
            **base, "source_id": "repo", "path": "src/main.py", "title": "Code",
            "type": "code", "owner": "example", "repo": "project", "commit": "a" * 40,
        }],
    }
    local_path = tmp_path / "local.json"
    github_path = tmp_path / "github.json"
    local_path.write_text(json.dumps(local))
    github_path.write_text(json.dumps(github))
    return local_path, github_path, local, github


@pytest.fixture
def github_server():
    server = Server("test-github")

    @server.list_tools()
    async def list_tools():
        return [Tool(name="get_file_contents", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name, arguments):
        assert name == "get_file_contents"
        assert arguments["sha"] == "a" * 40
        text = "Synthetic Python repository code."
        raw = text.encode()
        sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
        return CallToolResult(content=[
            TextContent(type="text", text=f"successfully downloaded text file (SHA: {sha})"),
            EmbeddedResource(type="resource", resource=TextResourceContents(
                uri="repo://example/project/sha/" + "a" * 40 + "/contents/src/main.py",
                text=text,
                mimeType="text/plain",
            )),
        ])

    return server


def test_combined_sources_reach_real_portfolio_mcp(
    manifests, github_server, tmp_path, monkeypatch
):
    local_path, github_path, _, _ = manifests

    async def fake_fetch(manifest, token):
        assert token == "test-token"
        async with create_connected_server_and_client_session(github_server) as session:
            return await build_github_index(manifest, session)

    monkeypatch.setenv("GIGBID_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(combined, "fetch_index", fake_fetch)
    output = tmp_path / "portfolio.json"
    items = combined.build_combined_index(local_path, github_path, output)
    write_index(items, output)
    results = anyio.run(retrieve_portfolio_evidence, ["Python"], output)
    assert {item.type for item in results[0]} == {"cv", "case_study", "code"}
    assert all(item.data_kind == "synthetic" for item in results[0])
    assert next(item for item in results[0] if item.type == "code").source.endswith(
        "/" + "a" * 40 + "/src/main.py"
    )


def test_conflicting_sources_and_invalid_metadata_fail_before_remote_call(manifests, tmp_path, monkeypatch):
    local_path, github_path, _, github = manifests
    github["documents"][0]["source_id"] = "case"
    github_path.write_text(json.dumps(github))
    fetch = pytest.fail

    async def never_fetch(*_args):
        fetch("remote should not be called")

    monkeypatch.setenv("GIGBID_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(combined, "fetch_index", never_fetch)
    with pytest.raises(ValueError, match="across manifests"):
        combined.build_combined_index(local_path, github_path, tmp_path / "out.json")
    github["documents"][0].update(source_id="repo", data_kind="real")
    github_path.write_text(json.dumps(github))
    with pytest.raises(ValidationError, match="rights_attested"):
        combined.build_combined_index(local_path, github_path, tmp_path / "out.json")


def test_preview_reports_content_and_metadata_changes_without_writing(manifests, tmp_path):
    local_path, _, local, _ = manifests
    output = tmp_path / "index.json"
    write_index(combined.build_combined_index(local_path, None, output), output)
    before = output.read_bytes()
    (tmp_path / "case.md").write_text("Changed synthetic Python case study.")
    local["documents"][0]["title"] = "Updated CV title"
    local_path.write_text(json.dumps(local))
    run = subprocess.run(
        [sys.executable, "-m", "rag.ingest.combined", "--local", str(local_path),
         "--output", str(output), "--preview"],
        text=True, capture_output=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "1 added, 1 removed, 1 updated, 0 unchanged" in run.stdout
    assert "No index written" in run.stdout
    assert output.read_bytes() == before


def test_failed_github_fetch_and_source_overwrite_preserve_output(manifests, tmp_path, monkeypatch):
    local_path, github_path, _, _ = manifests
    output = tmp_path / "index.json"
    output.write_text("unchanged")

    async def fail_fetch(_manifest, _token):
        raise ValueError("remote unavailable")

    monkeypatch.setenv("GIGBID_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(combined, "fetch_index", fail_fetch)
    with pytest.raises(ValueError, match="remote unavailable"):
        combined.build_combined_index(local_path, github_path, output)
    assert output.read_text() == "unchanged"
    with pytest.raises(ValueError, match="every manifest"):
        combined.build_combined_index(local_path, github_path, github_path)
    with pytest.raises(ValueError, match="every source"):
        combined.build_combined_index(local_path, None, tmp_path / "case.md")
    assert (tmp_path / "case.md").read_text() == "Synthetic Python case study."


def test_cli_rebuild_and_preview_deletion(manifests, tmp_path):
    local_path, _, local, _ = manifests
    output = tmp_path / "index.json"
    command = [
        sys.executable, "-m", "rag.ingest.combined", "--local", str(local_path),
        "--output", str(output),
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stderr
    assert len(json.loads(output.read_text())) == 2
    assert subprocess.run(command, capture_output=True, text=True, check=False).returncode != 0
    local["documents"].pop()
    local_path.write_text(json.dumps(local))
    preview = subprocess.run(command + ["--preview"], capture_output=True, text=True, check=False)
    assert "0 added, 1 removed, 0 updated, 1 unchanged" in preview.stdout
    assert len(json.loads(output.read_text())) == 2
    rebuilt = subprocess.run(command + ["--replace"], capture_output=True, text=True, check=False)
    assert rebuilt.returncode == 0, rebuilt.stderr
    assert len(json.loads(output.read_text())) == 1


def test_preview_rejects_duplicate_previous_ids_and_never_writes(manifests, tmp_path):
    local_path, _, _, _ = manifests
    output = tmp_path / "index.json"
    items = combined.build_combined_index(local_path, None, output)
    duplicated = [items[0].model_dump(mode="json")] * 2
    output.write_text(json.dumps(duplicated))
    before = output.read_bytes()
    run = subprocess.run(
        [sys.executable, "-m", "rag.ingest.combined", "--local", str(local_path),
         "--output", str(output), "--preview"],
        text=True, capture_output=True, check=False,
    )
    assert run.returncode != 0
    assert "portfolio evidence IDs must be unique" in run.stderr
    assert output.read_bytes() == before


def test_preview_without_existing_output_and_missing_manifests(manifests, tmp_path):
    local_path, _, _, _ = manifests
    output = tmp_path / "new.json"
    run = subprocess.run(
        [sys.executable, "-m", "rag.ingest.combined", "--local", str(local_path),
         "--output", str(output), "--preview"],
        text=True, capture_output=True, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert "2 added, 0 removed, 0 updated, 0 unchanged" in run.stdout
    assert not output.exists()
    with pytest.raises(ValueError, match="at least one"):
        combined.build_combined_index(None, None, output)
