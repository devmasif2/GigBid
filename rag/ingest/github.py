"""Build a portfolio index from explicitly selected files through GitHub MCP."""

import argparse
import hashlib
import os
import re
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import EmbeddedResource, TextContent, TextResourceContents
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent.tool_policy import call_allowed_tool, require_tool_access
from mcp_servers.portfolio.service import EvidenceItem
from rag.ingest.portfolio import SourceDocument, evidence_from_text, write_index

GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/x/repos"
MAX_FILE_BYTES = 1_000_000
TIMEOUT_SECONDS = 30


class GitHubDocument(SourceDocument):
    owner: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9-]+$")
    repo: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    type: Literal["repo_readme", "code"]

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            path.is_absolute()
            or "\\" in value
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("path must identify a relative repository file")
        return value


class GitHubManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    documents: list[GitHubDocument] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_sources(self) -> "GitHubManifest":
        keys = [(item.freelancer_id, item.source_id) for item in self.documents]
        if len(set(keys)) != len(keys):
            raise ValueError("source IDs must be unique within each freelancer")
        return self


async def build_github_index(
    manifest: GitHubManifest, session: ClientSession
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for document in manifest.documents:
        with anyio.fail_after(TIMEOUT_SECONDS):
            result = await call_allowed_tool(
                session,
                caller="github_ingest",
                server="github",
                tool="get_file_contents",
                arguments={
                    "owner": document.owner,
                    "repo": document.repo,
                    "path": document.path,
                    "sha": document.commit,
                },
            )
        if result.isError:
            raise ValueError(f"{document.source_id}: GitHub MCP returned a tool error")
        if (
            len(result.content) != 2
            or not isinstance(result.content[0], TextContent)
            or not isinstance(result.content[1], EmbeddedResource)
            or not isinstance(result.content[1].resource, TextResourceContents)
        ):
            raise ValueError(f"{document.source_id}: expected an embedded text file from GitHub MCP")
        match = re.fullmatch(
            r"successfully downloaded text file \(SHA: ([a-fA-F0-9]{40})\)",
            result.content[0].text,
        )
        if match is None:
            raise ValueError(f"{document.source_id}: unexpected GitHub MCP file metadata")
        text = result.content[1].resource.text
        raw = text.encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f"{document.source_id}: GitHub file exceeds size limit")
        # Git uses SHA-1 for blob identifiers, not as a security signature.
        blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False).hexdigest()
        if blob != match.group(1).lower():
            raise ValueError(f"{document.source_id}: GitHub file does not match its blob SHA")
        source = (
            f"https://github.com/{document.owner}/{document.repo}/blob/"
            f"{document.commit}/{quote(document.path, safe='/')}"
        )
        items.extend(evidence_from_text(document, text, source))
    ids = [item.id for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("generated evidence IDs are not unique")
    return items


async def fetch_index(manifest: GitHubManifest, token: str) -> list[EvidenceItem]:
    require_tool_access("github_ingest", "github", "get_file_contents")
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        with anyio.fail_after(TIMEOUT_SECONDS):
            async with (
                streamable_http_client(GITHUB_MCP_URL, http_client=client) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                return await build_github_index(manifest, session)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/local/portfolio.json"))
    parser.add_argument("--replace", action="store_true", help="Replace the existing complete index.")
    args = parser.parse_args()
    if args.manifest.resolve(strict=True) == args.output.resolve():
        raise ValueError("output must differ from manifest")
    manifest = GitHubManifest.model_validate_json(args.manifest.read_bytes())
    token = os.environ.get("GIGBID_GITHUB_TOKEN", "").strip()
    if not token:
        raise ValueError("GIGBID_GITHUB_TOKEN is required")
    items = anyio.run(fetch_index, manifest, token)
    write_index(items, args.output, replace=args.replace)
    print(f"Wrote {len(items)} portfolio chunks to {args.output}")


if __name__ == "__main__":
    main()
