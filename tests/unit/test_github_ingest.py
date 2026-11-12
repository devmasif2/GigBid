import hashlib
import json
from unittest.mock import AsyncMock

import anyio
import pytest
from mcp.server.lowlevel import Server
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult, EmbeddedResource, TextContent, TextResourceContents, Tool
from pydantic import ValidationError

from agent.tool_policy import ToolAccessDenied, require_tool_access
from mcp_servers.portfolio.service import Portfolio
from rag.ingest.github import GitHubManifest, build_github_index, main
from rag.ingest.portfolio import write_index


@pytest.fixture
def manifest_data():
    return {
        "version": 1,
        "documents": [{
            "source_id": "repo-1",
            "owner": "example",
            "repo": "project",
            "commit": "a" * 40,
            "path": "src/example.py",
            "freelancer_id": "demo",
            "title": "Synthetic Python code",
            "type": "code",
            "skills": ["Python"],
            "data_kind": "synthetic",
        }],
    }


def file_result(text):
    raw = text.encode("utf-8")
    digest = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
    return CallToolResult(content=[
        TextContent(type="text", text=f"successfully downloaded text file (SHA: {digest})"),
        EmbeddedResource(type="resource", resource=TextResourceContents(
            uri="repo://example/project/sha/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/contents/src/example.py",
            mimeType="text/plain",
            text=text,
        )),
    ])


@pytest.mark.anyio
async def test_ingestion_uses_mcp_and_preserves_provenance(manifest_data, tmp_path):
    server = Server("test-github")
    calls = []

    @server.list_tools()
    async def list_tools():
        return [Tool(name="get_file_contents", inputSchema={"type": "object"})]

    @server.call_tool()
    async def call_tool(name, arguments):
        calls.append((name, arguments))
        return file_result("def fictional_python():\n    return 'synthetic'\n")

    manifest = GitHubManifest.model_validate(manifest_data)
    async with create_connected_server_and_client_session(server) as session:
        items = await build_github_index(manifest, session)
    assert calls == [("get_file_contents", {
        "owner": "example", "repo": "project", "path": "src/example.py", "sha": "a" * 40,
    })]
    assert items[0].source == (
        "https://github.com/example/project/blob/" + "a" * 40 + "/src/example.py"
    )
    assert items[0].data_kind == "synthetic"
    output = tmp_path / "index.json"
    write_index(items, output)
    assert Portfolio(output).search_evidence("Python")[0].content == items[0].content


@pytest.mark.parametrize("path", ["../secret", "/absolute", "a/../b", "a//b", "a\\b", "a\nb"])
def test_invalid_paths_are_rejected(manifest_data, path):
    manifest_data["documents"][0]["path"] = path
    with pytest.raises(ValidationError, match="relative repository file"):
        GitHubManifest.model_validate(manifest_data)


def test_pinned_commits_rights_and_unique_sources_are_required(manifest_data):
    doc = manifest_data["documents"][0]
    doc["commit"] = "main"
    with pytest.raises(ValidationError):
        GitHubManifest.model_validate(manifest_data)
    doc["commit"] = "a" * 40
    doc["data_kind"] = "real"
    with pytest.raises(ValidationError, match="rights_attested"):
        GitHubManifest.model_validate(manifest_data)
    doc["rights_attested"] = True
    GitHubManifest.model_validate(manifest_data)
    manifest_data["documents"].append(doc.copy())
    with pytest.raises(ValidationError, match="unique"):
        GitHubManifest.model_validate(manifest_data)


@pytest.mark.anyio
@pytest.mark.parametrize("result,error", [
    (CallToolResult(isError=True, content=[]), "tool error"),
    (CallToolResult(content=[TextContent(type="text", text="directory")]), "embedded text"),
    (file_result(""), "empty"),
])
async def test_failed_or_nonfile_results_are_rejected(manifest_data, result, error):
    session = AsyncMock()
    session.call_tool.return_value = result
    with pytest.raises(ValueError, match=error):
        await build_github_index(GitHubManifest.model_validate(manifest_data), session)


@pytest.mark.anyio
async def test_untrusted_or_changed_blob_is_rejected(manifest_data):
    session = AsyncMock()
    result = file_result("original")
    result.content[1].resource.text = "tampered"
    session.call_tool.return_value = result
    with pytest.raises(ValueError, match="blob SHA"):
        await build_github_index(GitHubManifest.model_validate(manifest_data), session)
    result.content[0].text = '{"type":"symlink"}'
    with pytest.raises(ValueError, match="metadata"):
        await build_github_index(GitHubManifest.model_validate(manifest_data), session)


@pytest.mark.anyio
async def test_partial_failure_does_not_return_an_index(manifest_data):
    second = manifest_data["documents"][0].copy()
    second["source_id"] = "repo-2"
    manifest_data["documents"].append(second)
    session = AsyncMock()
    session.call_tool.side_effect = [
        file_result("first file"), CallToolResult(isError=True, content=[])
    ]
    with pytest.raises(ValueError, match="tool error"):
        await build_github_index(GitHubManifest.model_validate(manifest_data), session)
    assert session.call_tool.await_count == 2


@pytest.mark.anyio
async def test_github_call_timeout_is_explicit(manifest_data, monkeypatch):
    async def hang(*args, **kwargs):
        await anyio.sleep(1)

    session = AsyncMock()
    session.call_tool.side_effect = hang
    monkeypatch.setattr("rag.ingest.github.TIMEOUT_SECONDS", 0.01)
    with pytest.raises(TimeoutError):
        await build_github_index(GitHubManifest.model_validate(manifest_data), session)


def test_github_policy_allows_only_file_reads():
    require_tool_access("github_ingest", "github", "get_file_contents")
    with pytest.raises(ToolAccessDenied):
        require_tool_access("github_ingest", "github", "push_files")


def test_cli_requires_token_before_fetch_or_writing(manifest_data, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_data))
    output = tmp_path / "index.json"
    output.write_text("unchanged")
    monkeypatch.delenv("GIGBID_GITHUB_TOKEN", raising=False)
    monkeypatch.setattr("sys.argv", [
        "github", str(manifest), "--output", str(output), "--replace",
    ])
    with pytest.raises(ValueError, match="GIGBID_GITHUB_TOKEN"):
        main()
    assert output.read_text() == "unchanged"


def test_cli_fetch_failure_never_replaces_existing_index(manifest_data, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_data))
    output = tmp_path / "index.json"
    output.write_text("unchanged")

    async def fail_fetch(manifest, token):
        raise ValueError("remote failure")

    monkeypatch.setenv("GIGBID_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr("rag.ingest.github.fetch_index", fail_fetch)
    monkeypatch.setattr("sys.argv", [
        "github", str(manifest), "--output", str(output), "--replace",
    ])
    with pytest.raises(ValueError, match="remote failure"):
        main()
    assert output.read_text() == "unchanged"
