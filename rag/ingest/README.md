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

## GitHub MCP repository files

The separate GitHub loader reads explicitly selected README or code files through the official
[GitHub MCP server](https://github.com/github/github-mcp-server). It requires a GitHub token
authorized for the remote MCP server and the selected repository. Configure a narrowly scoped,
read-only token locally in `GIGBID_GITHUB_TOKEN`; never paste it into chat, a manifest, or Git.
The loader sends it only to GitHub's fixed HTTPS MCP repository endpoint, with redirects and
environment proxies disabled. GitHub may require an eligible account; authorization and
remote availability depend on its service. Private repository files are returned to this local
process and written in plaintext to the index. This has not been tested with a live token.

Create a separate manifest in a private, ignored directory:

```json
{
  "version": 1,
  "documents": [{
    "source_id": "fictional-code",
    "owner": "example",
    "repo": "example-project",
    "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "path": "src/example.py",
    "freelancer_id": "demo-analyst",
    "title": "Fictional Python example",
    "type": "code",
    "skills": ["Python"],
    "data_kind": "synthetic"
  }]
}
```

Replace the example with an authorized repository and its full 40-character lowercase commit
SHA. Types are `repo_readme` or `code`; metadata, source IDs, data labels, and `rights_attested`
follow the same rules as local ingestion. Up to 20 files are selected individually, not crawled.
The tool accepts embedded text files up to 1,000,000 bytes; directories, binaries, symlinks,
large-file links, empty files, and unexpected responses fail explicitly. It checks the returned
Git blob SHA against the text; this checks consistency, not authenticity or ownership. All
files must succeed before the output is written.
The entire connection and import has a 30-second deadline; failures are surfaced without
automatic retries. Retry manually after checking the cause.

```bash
# Set GIGBID_GITHUB_TOKEN privately in your shell first.
uv run python -m rag.ingest.github data/local/github-manifest.json \
  --output data/local/github-portfolio.json
```

`--replace` is required to overwrite an existing output. This command produces a **separate full
index**; use the combined rebuild below to search both local and GitHub evidence together.
Each chunk has a commit-pinned GitHub source link, but a repository link does not establish
authorship, contribution, permission, or factual accuracy. Repository text is untrusted and may
contain instructions or secrets: review and redact files before indexing. The rights attestation
is an operator assertion, not a verification. No files are executed.

## Combined index and preview

The combined command takes either or both existing manifest formats and builds one complete
Portfolio MCP index. Source IDs must be unique per freelancer **across both manifests**.
Local paths still resolve relative to the local manifest, and GitHub access still requires
the token. If any input is invalid, missing, or unavailable, no index is written.

```bash
uv run python -m rag.ingest.combined \
  --local data/local/my-portfolio/manifest.json \
  --github data/local/github-manifest.json \
  --output data/local/portfolio.json --preview

# After reviewing the preview, build (use --replace only for an existing index).
uv run python -m rag.ingest.combined \
  --local data/local/my-portfolio/manifest.json \
  --github data/local/github-manifest.json \
  --output data/local/portfolio.json --replace
```

Omit either `--local` or `--github` to build from just that source. Preview fetches and validates
all sources but never writes an index; it compares against the chosen output, or an empty index
if it does not exist. Counts show added and removed chunk IDs, metadata-updated chunks with
the same IDs, and unchanged chunks. Editing text may appear as both an addition and a removal.
Malformed existing indexes or duplicate IDs fail rather than being ignored. Review the content,
not just the counts. Preview does not guarantee a later rebuild will use unchanged files.

The API reads the index selected by `GIGBID_PORTFOLIO_PATH`; its read-only portfolio search
and web panel show up to five matched chunks and their declared provenance. Search does not
list the entire index or edit data. The API has **no authentication or tenant isolation** and
must remain local; anyone with API access can search private evidence. Rebuilds are full, not
incremental, and require every selected GitHub file to be accessible again.

Neither loader provides UI upload, automatic rights verification, semantic chunking, incremental
indexing, a vector database, or production-ready multi-user storage. There is no OCR or automatic
redaction, deduplication, or independent fact checking.
