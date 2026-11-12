# Local portfolio ingestion

The local CLI builds a complete Portfolio MCP JSON index from UTF-8 Markdown and text
documents and text-based PDFs. Keep documents, manifests and generated indexes in `data/local/` (git-ignored);
do not commit private portfolios or client material. The CLI runs locally; opt-in model
retrieval sends indexed text to the configured loopback Ollama service. The API has no
authentication and must not be exposed publicly.

Create a folder such as `data/local/my-portfolio/`, put your documents there, and create
`manifest.json` in that folder. This illustrative example describes fictional content:

```json
{
  "version": 1,
  "documents": [
    {
      "source_id": "fictional-dashboard",
      "path": "dashboard.md",
      "freelancer_id": "demo-analyst",
      "title": "Fictional dashboard",
      "type": "case_study",
      "skills": ["Python", "analytics"],
      "data_kind": "synthetic",
      "project": "Example",
      "date": "2026-01-15",
      "client_industry": "retail",
      "outcome": null
    }
  ]
}
```

Paths are relative to the manifest and must resolve to files within its directory. Supported
extensions are `.md`, `.txt`, and `.pdf`; files must be at most 2,000,000 bytes. Markdown
and text files must be nonempty UTF-8. PDFs must be unencrypted, contain 1–100 pages, and
have no more than 2,000,000 extracted text characters. Every PDF page must have extractable
text; blank or image-only pages fail the whole rebuild, because OCR is not provided.
PDF text extraction can omit or reorder material even on pages with some text, especially
tables, columns, images, and unusual fonts. Review the generated index against the original
before relying on it; evidence quotes refer to extracted text, not verified PDF coordinates.
Page and text limits are checked during parsing and do not sandbox the parser or bound its peak
memory or runtime. Process only trusted local files.
Source IDs use letters, digits, dots, underscores or hyphens and must be unique per freelancer.
Types are `cv`, `case_study`, `repo_readme`, `code`, `review`, and `proposal`. The optional
date is ISO 8601 (`YYYY-MM-DD`); project, client industry and outcome are user-provided
metadata, not extracted or verified facts. Only enter metadata you are authorized to use.

`data_kind` is required: `synthetic`, `unverified`, or `real`. For `real`, the manifest must
also include `"rights_attested": true`: this is the operator's declaration that the material
is real and they have permission to process it, **not independent verification** of ownership,
truth, consent, or publication rights. Anyone who can edit the manifest can make that
declaration; only use it for genuinely authorized real evidence. The existing bid graph treats
`real` as eligible for its approval path. Synthetic and unverified evidence cannot pass that
gate. Review all generated claims and client privacy requirements yourself.

```bash
uv run python -m rag.ingest.portfolio data/local/my-portfolio/manifest.json
GIGBID_PORTFOLIO_PATH=data/local/portfolio.json uv run python -m mcp_servers.portfolio.server
```

Set `GIGBID_PORTFOLIO_PATH` on the API process instead to use the index in bid runs. The
default output `data/local/portfolio.json` is ignored by Git. `--output PATH` changes the
destination; choose a protected, ignored location, since the tool cannot determine whether a
custom path is private. The output is a complete replacement corpus, not merged with starter
data. Existing output is never overwritten unless `--replace` is supplied:

```bash
uv run python -m rag.ingest.portfolio data/local/my-portfolio/manifest.json --replace
```

Rebuild after editing the manifest or documents. The full index is validated before an atomic
write, and files are created with owner-only permissions. Each chunk has a deterministic ID
based on freelancer, source ID, chunk position and content hash; changed text gets a new ID.
IDs and exact chunk text are preserved through Portfolio MCP for the existing quotation
verifier. Metadata and document contents remain in plaintext on disk. Keep the manifest to map
the `local-manifest:<source_id>` provenance label back to its source; the label is not a
verified citation or a published link. Changing source ordering, chunk boundaries, or content
can change IDs; do not treat them as permanent external references.

This is not a GitHub integration, UI upload, automatic rights checker, semantic
chunker, incremental index, vector database, or production-ready multi-user storage. It does
not perform OCR, redaction, deduplication of document contents, or independent fact checking.
