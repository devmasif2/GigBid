# Reviewer guide

GigBid is a local, synthetic-data prototype. Do not enter credentials or private client data.
The API has no secure authentication and must remain bound to localhost.

## Start

Requirements: Python 3.11+, `uv`, Node.js 20.19+ (or 22.12+), and npm.

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

Open the Vite URL, normally `http://127.0.0.1:5173`.

## Optional simulator mode

For simulator messages and pipeline data, run:

```bash
make gigsim
GIGBID_MARKETPLACE_MODE=gigsim GIGSIM_API_TOKEN=gigsim-dev-token \
  uv run uvicorn apps.api.main:app --reload
```

The simulator is local and synthetic; it is not the instructor's GigSim or Upwork.

## Validation and evidence

```bash
uv run --locked ruff check .
uv run --locked pytest -q
cd apps/web && npm run build && npm run test:e2e
cd ../.. && make eval
```

The expected current backend result is 340 passed and 2 skipped. The browser suite uses mocked
API responses and currently covers eight scenarios. Evaluation output is written to the ignored
`evals/results/` directory.

Follow [DEMO_WALKTHROUGH.md](./DEMO_WALKTHROUGH.md) for a three-minute tour. Read
[TECHNICAL_WRITEUP.md](./TECHNICAL_WRITEUP.md) for architecture and findings, and
[RND_REPORT.md](./RND_REPORT.md) for the limitations and research framing.

## Safety boundaries

Approving a bid creates only a local draft. It does not submit a proposal or spend Connects.
Approving a conversation review does not send a message. Synthetic and unverified evidence cannot
pass the real-evidence gate. Do not interpret local analytics as live marketplace outcomes.
