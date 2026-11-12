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
crash/restart recovery has not been demonstrated. Do not describe this as production-ready
durability or exactly-once external submission.

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
