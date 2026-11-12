# GigBid

GigBid is a human-approved freelancer copilot for finding jobs, assessing fit and risk, grounding proposals in portfolio evidence, and managing client conversations.

## Development status

The project includes Portfolio, local Marketplace, and local Workspace MCP servers; deterministic
analysis nodes; bid and conversation LangGraph workflows with approval interrupts; API start,
stream, and resume endpoints; and retrieval components V0–V3 and V8. The local portfolio and job
fixtures are explicitly synthetic. Only evidence marked `real` can reach the bid approval gate.
The Marketplace server defaults to a static sample adapter; set `GIGBID_MARKETPLACE_MODE=gigsim`
to use [`gigsim_local`](gigsim_local/README.md), our own marketplace simulator (not the
instructor's GigSim, and not Upwork).

Portfolio search defaults to lexical matching. An experimental local Ollama hybrid mode combines
embeddings and BM25 and is opt-in. An optional local cross-encoder can rerank its candidates;
see [evaluation instructions](evals/README.md#local-portfolio-search).
It does not turn synthetic or unverified records into real evidence, and still requires human review.

## Run locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
uv run uvicorn apps.api.main:app --reload
```

For the API to persist checkpoints in PostgreSQL, set `DATABASE_URL`; without it, the graph uses
in-memory checkpoints. The local Compose stack provides PostgreSQL and configures the API to use
it:

```bash
docker compose -f infra/docker-compose.yml up --build
```

The API health check is at `http://127.0.0.1:8000/health`.
The read-only local sample jobs are available at `GET /jobs` (optionally with a `query` parameter)
and `GET /jobs/{job_id}` through the local Marketplace MCP server. These fixtures are synthetic and
are not GigSim listings. Marketplace failures return HTTP 503; missing jobs return 404.
The development API can start workflows at `POST /graphs/bid/start` or
`POST /graphs/conversation/start` with `{"thread_id":"...","input":{...}}`, then resume an approval
at `POST /graphs/{bid|conversation}/{thread_id}/approval` with `{"action":"approve"}` or
`{"action":"reject"}`. `GET /graphs/{bid|conversation}/{thread_id}` retrieves a checkpoint and
pending interrupt; unknown threads return 404. After an approved run fails at the draft-creation
step (HTTP 503), `POST /graphs/{bid|conversation}/{thread_id}/continue` resumes it. Use `POST /graphs/{bid|conversation}/stream` with the same start payload for
Server-Sent Events (`update` events per graph node and a final `complete` event; an `error` event
ends a run if Portfolio MCP is unavailable). Bid fit analysis starts the local Portfolio MCP
server over stdio. This API has no authentication and defaults to in-memory checkpoints; keep it
local and do not deploy it publicly.

For a conversation review, `{"action":"edit","message":"..."}` saves the edited reply and
returns a new approval interrupt with heuristic validation results. Review the reply yourself:
the checks do not detect all unsupported claims or enforce live marketplace policy. Approving,
rejecting, or editing a conversation is local only and does not send a message.

The read-only simulator pipeline is available at `GET /pipeline` and in the web interface. It
shows proposal stages and simulated Connects; refresh manually to update it. Its two underlying
reads are not atomic. Sample mode and simulator outages return 503; viewing the pipeline never
confirms a proposal or spends Connects.

Run the Portfolio MCP server over stdio with:

```bash
uv run python -m mcp_servers.portfolio.server
```

Run the local sample Marketplace MCP server over stdio with:

```bash
uv run python -m mcp_servers.marketplace.server
```

Run the local Workspace MCP mock over stdio with:

```bash
uv run python -m mcp_servers.workspace.server
```

In the default `sample` mode the Marketplace server uses synthetic starter fixture jobs. To run
against the local simulator:

```bash
make gigsim                                   # terminal 1: simulator on 127.0.0.1:8100
GIGBID_MARKETPLACE_MODE=gigsim GIGSIM_API_TOKEN=gigsim-dev-token \
  uv run uvicorn apps.api.main:app --reload   # terminal 2
```

Workspace data is in-memory only; no external calendar events are created and no email is
sent. See [`docs/TOOLS.md`](docs/TOOLS.md) for the current tool inventory and limitations.

Set `GIGBID_PORTFOLIO_PATH` to use a different JSON evidence file. The
[local ingestion CLI](rag/ingest/README.md) can build one from explicitly labelled Markdown,
text, and text-based PDF documents. It requires a rights attestation for material declared real; this is not
independent verification. Keep private documents and generated indexes out of Git.
An opt-in GitHub MCP loader also supports selected README and code files at pinned commits;
its authenticated remote setup has not yet been live-tested. See the same ingestion guide.

### Synthetic component evaluations

Run `make eval` to regenerate synthetic retrieval, simulator risk and isolated simulator outcome reports in
`evals/results/`. These are small, local component smoke tests, not the required full benchmark,
real-world outcomes, or the instructor's hidden test. See [`evals/README.md`](evals/README.md) for
metrics, data provenance, variant configurations and limitations.

### Web interface

With the API running, start the React/Vite frontend in a second terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Vite proxies `/api` calls to the local FastAPI service. The current interface implements the
synthetic opportunity inbox, job details, streamed analysis, local proposal review, and a
simulator message viewer with local reply review. Message reads require `gigsim` mode; in sample
mode they show an unavailable error. Approving a reply only records the review and never sends it.
The browser
tracks one run for refresh recovery; restart recovery requires a persistent checkpointer and remains
unverified. The review supports editing the cover letter and screening answers, then rechecking
them before approval. Its deterministic claim checks are limited, so the user must review all
claims. Approving a bid creates one idempotent local draft in a SQLite file
(`GIGBID_MARKETPLACE_DB`, default `data/local/marketplace.sqlite3`); it does not submit a proposal. See [`apps/web/README.md`](apps/web/README.md) for frontend-specific setup.

## Assignment

See the local assignment brief and progress checklist in `local_docs/` (these files are intentionally git-ignored). Dataset source and handling notes are in [`docs/DATA_CARD.md`](docs/DATA_CARD.md).

The current build is not deployment-ready: the API has no authentication; database crash/resume
has not been demonstrated; GigSim/Upwork, most frontend screens, corpus ingestion, model-backed RAG
evaluation, CI gates, worker scheduling, and remaining submission deliverables are not complete.
