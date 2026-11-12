# GigBid web

React + Vite + TypeScript frontend. The first implemented screen is the local synthetic-job
inbox, which supports search, job details, streamed bid-workflow analysis, and local proposal
review. Only the most recently tracked bid thread is saved in browser local storage; proposal
contents remain in the API checkpointer.

## Run locally

Requires Node.js 20.19+ (or 22.12+) and npm.

Start the FastAPI backend in the repository root:

```bash
uv run uvicorn apps.api.main:app --reload
```

In another terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Open the address printed by Vite (normally `http://127.0.0.1:5173`). The Vite development server
proxies `/api` requests to `http://127.0.0.1:8000`; the backend stays separate.

Run `npm run typecheck` or `npm run build` to validate the frontend. A pending bid can be recovered
after a page refresh while its API checkpoint exists. In-memory checkpoints disappear on API
restart; PostgreSQL persistence is optional and its crash/recovery behavior is not yet verified.
The current UI is a prototype with an inbox/detail view and proposal review panel; it uses clearly
labeled synthetic fixtures. The default synthetic portfolio cannot reach the proposal approval gate.
Authentication, the remaining assignment screens, production deployment, and live marketplace
connections are not implemented.
