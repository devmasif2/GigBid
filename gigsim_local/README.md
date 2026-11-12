# gigsim_local — local GigSim stand-in

A small marketplace simulator **written by us**, not the instructor's GigSim. It exists so GigBid
can be developed, tested and demonstrated end to end (jobs, clients, Connects, proposals, messages,
rate limits, outages, a mid-project policy change) without a real platform. The endpoint design
below is our own assumption of what such an API looks like. If the instructor's simulator is
provided later, GigBid's marketplace adapter is the only code that should need to change; any
number measured here must be labelled "local GigSim stand-in", never "GigSim".

All data is synthetic and deterministic for a given seed.

## Run

```bash
make gigsim                      # or: uv run python -m gigsim_local
GIGSIM_PORT=8100 GIGSIM_USER_TOKENS="my-token:me" GIGSIM_ADMIN_TOKEN="change-me" \
  uv run python -m gigsim_local
```

| Variable | Default | Meaning |
|---|---|---|
| `GIGSIM_HOST` / `GIGSIM_PORT` | `127.0.0.1` / `8100` | Bind address |
| `GIGSIM_USER_TOKENS` | `gigsim-dev-token:dev-user` | `token:user` pairs (comma separated) |
| `GIGSIM_ADMIN_TOKEN` | `gigsim-admin-token` | Operator token for `/sim/*` |
| `GIGSIM_SEED` | `1234` | World seed (same seed, same world) |
| `GIGSIM_RATE_LIMIT_PER_MINUTE` | `60` | Per-user request budget |
| `GIGSIM_ERROR_RATE` | `0.0` | Fraction of requests that fail with 503 |

The defaults are development tokens for synthetic data. Do not expose the simulator publicly with
them. GigBid selects this adapter with `GIGBID_MARKETPLACE_MODE=gigsim`, `GIGSIM_BASE_URL` and
`GIGSIM_API_TOKEN`.

## Contract

All routes except `/health` need `Authorization: Bearer <token>`. Writes need an
`Idempotency-Key` header (8–200 characters).

| Route | Purpose |
|---|---|
| `GET /jobs?query&limit&offset&since_hour` | Jobs posted so far, newest first |
| `GET /jobs/{id}` | One job (404 if unknown or not yet posted) |
| `GET /clients/{id}/history` | Public client stats and reviews |
| `GET /account/connects` | Connects balance (starts at 200) |
| `GET /policy` | Current marketplace rules and costs |
| `POST /proposals` | Create a **draft**; free, no Connects spent |
| `GET /proposals`, `GET /proposals/{id}` | The caller's proposals |
| `POST /proposals/{id}/confirm` | Simulates the freelancer confirming on the platform; spends Connects |
| `GET /messages?proposal_id`, `POST /messages` | Conversation |
| `GET /events?after_id` | Status and message events (for a pipeline board) |

Operator routes (`/sim/*`, admin token): `POST /sim/tick {"hours": n}` advances the simulated
clock; `POST /sim/faults {"fail_next": n, "error_rate": r}` injects 503s;
`POST /sim/policy {...}` applies a policy update; `GET /sim/ground-truth` exposes hidden labels
for evaluation; `GET /sim/outcomes` returns reply and hire rates; `POST /sim/reset` restarts.

Behaviour worth knowing:

- **Idempotency.** Replaying a key with the same request returns the stored response and sets
  `Idempotent-Replay: true`; the same key with a different request is `409`. Confirming twice
  spends Connects once.
- **Rate limits.** Over the per-user budget returns `429` with `Retry-After`.
- **Errors.** Injected outages return `503` with `Retry-After: 1`. `/health` is exempt.
- **Simulated time.** Nothing progresses until `tick`. A confirmed proposal moves through
  `submitted → viewed → replied → interview → hired`, or `viewed → lost`, with client messages
  arriving on the way. About a fifth of the jobs only appear as the clock advances.
- **Policy update (the "change request").** `connects_multiplier`, `max_cover_letter_chars`,
  `require_screening_answers` and `banned_phrases` can be changed at runtime. They are enforced on
  `confirm` and visible in `GET /policy`, so a client that reads policy from the API needs no code
  change for those structured rules. Updates are validated before any changes are applied.
  GigBid rechecks policy before creating a draft but does not confirm it; a concurrent policy
  change between that check and draft creation is still possible.

## What clients do (and do not) reveal

Each client has hidden preferences: must-have skills, a budget ceiling, whether it dislikes generic
openings, and a reply threshold. They are never returned by user routes, only by
`/sim/ground-truth`. About 12% of jobs are hidden-labelled scams (unpaid work, off-platform
contact, guaranteed results, prompt injection); their client messages push WhatsApp/payment
outside the platform, and the injection variant adds an instruction to ignore previous
instructions. These are test fixtures for safety checks.

## Reply model

Replies are a deterministic function, documented in
[`reply_model.py`](reply_model.py), not an LLM. A proposal scores higher when it names the client's
must-have skills, overlaps the job title, includes concrete numbers, answers the screening
questions and is priced under the client's ceiling. It scores lower for generic openings (when the
client dislikes them), very short text, an excessive price, and off-platform or guaranteed-result
language. A fixed per-proposal noise term is added, then the score is compared with the client's
threshold to decide ignored / replied / interview / hired.

This is a stand-in. It rewards what we chose to reward, so a good reply rate here shows that a
proposal fits the model, not that it would win real work.

## Limits

- In-memory state; a restart or `/sim/reset` returns to the seeded world.
- One process, no persistence, no multi-tenant isolation beyond per-token accounts.
- The reply model is simple and may be gamed by keyword stuffing; the proposal verifier, not the
  simulator, is what keeps claims truthful.
