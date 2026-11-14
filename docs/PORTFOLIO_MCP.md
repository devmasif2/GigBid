# Portfolio MCP server

Run the local Portfolio MCP server over stdio:

```bash
uv run python -m mcp_servers.portfolio.server
```

The server reads the configured portfolio index (`GIGBID_PORTFOLIO_PATH`, defaulting to the
synthetic sample data) and exposes `search_evidence`, `get_case_study`, `list_skills`, resources
for portfolio cases and proposals, and the screening-question prompt. Search results preserve
evidence IDs, provenance, data kind, skills, and rights-attestation metadata.

The bid graph is restricted to `search_evidence` by the fail-closed client tool policy. Only
records explicitly marked `real` can pass the approval gate. The default sample records are
synthetic and are intentionally unsuitable for claiming real experience.

For ingestion from Markdown, text-based PDF, repository README/code, reviews, or proposals, see
[`rag/ingest/README.md`](../rag/ingest/README.md). Keep private documents and generated indexes
outside Git. This local stdio server has no authentication and must not be exposed directly to
untrusted clients.
