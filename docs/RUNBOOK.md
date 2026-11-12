# GigBid runbook

## Local startup

Requirements: Python 3.11+, `uv`, and Node.js 22+ for the web build.

```bash
uv sync --extra dev
uv run uvicorn apps.api.main:app --reload
```

In another terminal:

```bash
cd apps/web
npm ci
npm run dev
```

The API health endpoint is `GET /health`. The frontend runs on the Vite port shown in
the terminal and proxies `/api` requests to the local API.

## PostgreSQL checkpoints

The API uses an in-memory checkpointer unless `DATABASE_URL` is set. For the local Compose
database:

```bash
docker compose -f infra/docker-compose.yml up --build
```

The current repository has configuration and tests for the PostgreSQL checkpointer, but
the optional integration test demonstrates checkpoint survival across two checkpointer
instances when PostgreSQL is available:

```bash
DATABASE_URL=postgresql://gigbid:gigbid@127.0.0.1:5432/gigbid \
  uv run --locked pytest -q tests/integration/test_postgres_checkpoint_recovery.py
```

This proves persisted approval state across checkpointer recreation, not process-kill recovery,
multi-user isolation, or exactly-once external submission. Do not describe it as production-ready
durability.

## Evaluation and CI

Run the same local gates as CI:

```bash
uv run --locked ruff check .
uv run --locked pytest -q
cd apps/web && npm ci && npm run build
cd apps/web && npx playwright install chromium && npm run test:e2e
cd ../..
make eval
```

Evaluation outputs are synthetic and written to the ignored `evals/results/` directory. They
measure components, not live Upwork behavior, semantic claim truth, or independent proposal
quality.

The browser smoke tests mock the jobs API and cover inbox rendering, job selection, and explicit
marketplace outage feedback. They do not prove the full approval flow or live API behavior.

## Tracing and usage measurement

Graph start, approval, continue, and SSE endpoints accept an optional `X-Trace-Id` UUID. If
omitted, the API generates one and returns it in an `observability` object. The frontend uses
the graph thread UUID as its trace ID and stores the final SSE trace summary in the run state.
Each graph update records elapsed milliseconds and a deterministic text-token estimate.
`cost_usd` is explicitly `null` for these local deterministic/model-agnostic paths; no provider
billing cost is inferred. Token estimates are not provider tokenizer counts.

Example response shape:

```json
{
  "observability": {
    "trace_id": "uuid",
    "latency_ms": 12.3,
    "token_estimate": 42,
    "cost_usd": null,
    "spans": [{"name": "graph.start", "latency_ms": 12.1, "token_estimate": 42, "cost_usd": null}]
  }
}
```

Use the existing synthetic evaluation reports for component latency. They are local measurements
and do not establish provider token cost, production p95 budgets, or live marketplace latency.
`make eval` also runs the graph observability benchmark, which records local conversation-graph
p50/p95 latency and deterministic token estimates. It intentionally reports provider cost as
unavailable.

## Degraded mode and recovery

- Portfolio MCP failure: bid analysis returns an explicit service error; it does not silently
  fabricate evidence.
- Marketplace sample or simulator outage: API returns an explicit unavailable response.
- Pending graph approvals: query the graph thread endpoint. With in-memory checkpoints, restart
  loses state; with PostgreSQL configured, recovery is intended but not yet verified.
- Failed approved draft creation: use the graph `continue` endpoint with the same thread ID.
  Draft creation is idempotent, but no real proposal or message is sent.

## Safety and live-mode limits

The API has no authentication or tenant isolation and must remain local until those controls are
implemented. Approval is required before the local draft write; the application does not submit
proposals, spend Connects, or send messages. Do not use browser automation, session cookies, or
scraping for live marketplace access. Credentials and private portfolio data must stay in local
environment variables or ignored files.
