# MCP Tool Inventory

The local development servers use stdio and currently have no HTTP authentication. Do not expose
stdio servers directly to untrusted clients. The Marketplace server has two adapters chosen by
`GIGBID_MARKETPLACE_MODE`: `sample` (static starter jobs, the default) and `gigsim` (our local
simulator, [`gigsim_local`](../gigsim_local/README.md), over HTTP). Neither is the instructor's
GigSim nor a live Upwork adapter. The only write is a proposal draft.

| Name | Server | Access | MCP annotations | Auth |
|---|---|---|---|---|
| `search_evidence` | Portfolio | Read | `readOnlyHint=true` | Local stdio; no auth |
| `get_file_contents` | Official GitHub MCP (opt-in ingestion CLI) | Read | Server advertises read-only | GitHub bearer token in local environment; live auth unverified |
| `get_case_study` | Portfolio | Read | `readOnlyHint=true` | Local stdio; no auth |
| `list_skills` | Portfolio | Read | `readOnlyHint=true` | Local stdio; no auth |
| `search_jobs` | Marketplace | Read | `readOnlyHint=true` | Local stdio; no auth |
| `get_job` | Marketplace | Read | `readOnlyHint=true` | Local stdio; no auth |
| `get_client_history` | Marketplace (`gigsim` mode only) | Read | `readOnlyHint=true` | Local stdio; no auth |
| `get_connects_balance` | Marketplace (`gigsim` mode only) | Read | `readOnlyHint=true` | Local stdio; no auth |
| `list_proposals` | Marketplace (`gigsim` mode only) | Read | `readOnlyHint=true` | Local stdio; no auth |
| `list_messages` | Marketplace (`gigsim` mode only) | Read | `readOnlyHint=true` | Local stdio; no auth |
| `get_marketplace_policy` | Marketplace (`gigsim` mode only) | Read | `readOnlyHint=true` | Local stdio; no auth |
| `create_proposal_draft` | Marketplace | Write (draft only) | `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false` | Local stdio; no auth |
| `get_free_slots` | Workspace (local mock) | Read | `readOnlyHint=true` | Local stdio; no auth |
| `create_tentative_hold` | Workspace (local mock) | Write (mock only) | `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=true` | Local stdio; no auth |
| `create_email_draft` | Workspace (local mock) | Write (mock only) | `readOnlyHint=false`, `destructiveHint=false`, `idempotentHint=true` | Local stdio; no auth |

## Client tool policy

The integrated callers use a fail-closed allowlist in `agent/tool_policy.py`. The `github_ingest`
CLI may call only GitHub `get_file_contents` at pinned commits. The `fit_matcher`
may call only Portfolio `search_evidence`; the job inbox API may call only Marketplace
`search_jobs` and `get_job`; the portfolio viewer may call only Portfolio `search_evidence`;
the risk assessor may call only Marketplace `get_client_history`;
the policy reader may call only `get_marketplace_policy`; the message inbox may call only
`list_messages`; the pipeline viewer may call only `list_proposals` and `get_connects_balance`;
and the post-approval `proposal_publisher`
may call only Marketplace `create_proposal_draft`. The policy checks both caller and server as well as tool name before
dispatch, logs denials without arguments, and denies unknown callers and tools. These checks are
client-side controls for these code paths, not MCP server authentication or an isolation
boundary against arbitrary Python code. Other agents, resource and prompt access, and future
integrations still need explicit policies before they are connected.

## `create_proposal_draft`

The only Marketplace write. It never submits a proposal, sends a message, or spends Connects.

- **Dry run by default.** `dry_run` defaults to `true` and returns what would be saved (the draft
  and `connects_cost_if_submitted`) without writing a draft; `connects_spent` is always 0 and
  `external_action_taken` is always `false`. The Connects cost comes from the job, adjusted by
  the current simulator policy multiplier in `gigsim` mode, not the caller.
- **Idempotent.** Writes are keyed by `idempotency_key` (8–200 chars) in a local SQLite file
  (`GIGBID_MARKETPLACE_DB`, default `data/local/marketplace.sqlite3`, git-ignored). A retry with the
  same key and payload returns `already_exists`; the same key with a different payload is an error.
  The graph derives the key from the job ID, price, and approved text, so retries (including the
  client's automatic transport retries) cannot create a second draft.
- **Validated.** The job must exist in the Marketplace fixtures; `price` must be in (0, 1,000,000];
  the cover letter is 1–20,000 characters.
- **Append-only audit log.** Every call that reaches the tool (including dry runs and failures)
  records user, tool, arguments, result, and trace ID. SQLite triggers abort `UPDATE`/`DELETE` on
  the table. The cover letter is stored only as a hash prefix and length, not as text. The user is
  `GIGBID_USER_ID` (default `local-user`), set by the server environment, not by tool arguments.
  The caller may pass `trace_id`; the graph does not propagate trace IDs yet.
- **Per-user rate limit.** At most `GIGBID_MARKETPLACE_RATE_LIMIT` (default 20) calls per user per
  minute, counted from the audit log. This is a local guard, not GigSim's real limit, and the
  check-then-write is not atomic across concurrent processes.
- **Human approval.** The bid graph reaches this tool only after the interrupt-based human approval
  node returns `approve`, and the UI states that the result is a draft. The server has no
  independent proof of approval: any local caller with access to the stdio server can invoke it.
  Rejected and needs-attention outcomes never reach it.

## Portfolio resources and prompt

| Name | Server | Access | Auth |
|---|---|---|---|
| `portfolio://case/{case_id}` | Portfolio resource template | Read | Local stdio; no auth |
| `portfolio://proposal/{proposal_id}` | Portfolio resource template | Read | Local stdio; no auth |
| `answer_screening_question` | Portfolio prompt | Read | Local stdio; no auth |

## Trust and current limitations

- **GitHub MCP:** GitHub's own server provides repository access using the operator's token;
  results are untrusted content, not proof of authorship or rights. Only the fixed official
  HTTPS endpoint is used and only explicitly selected files are requested. The integration
  is tested against an in-memory MCP test server, not with live GitHub credentials.
- Portfolio results are read from the configured local JSON file. The default content is synthetic
  starter data and must not be used to claim real freelancer experience.
- The bid graph calls Portfolio `search_evidence` through a local stdio MCP session; the fit branch
  is constrained by the client tool policy. Each complete read-only retrieval attempt, including process startup,
  initialization, and searches, has a 10-second timeout. Connection failures and timeouts are retried
  at most twice with 0.1s and 0.2s backoff; protocol errors, failed tool calls, and malformed evidence
  are not retried. Exhaustion stops the run and is reported as an error. Shared sessions, other
  agents' tool policies, and queued recovery are pending.
- **Adapters.** In `sample` mode the `gigsim`-only read tools return a tool error ("not
  available"), never invented data. In `gigsim` mode the server talks HTTP to the simulator with
  `GIGSIM_BASE_URL` and `GIGSIM_API_TOKEN`; the adapter maps 401/403, 404, 429 (with `Retry-After`),
  other 4xx and 5xx/timeouts to distinct errors. Marketplace policy (costs, required answers,
  banned phrases) is read through `get_marketplace_policy` rather than hard-coded, so a rule
  change in the marketplace needs no code change for the supported structured fields. The graph
  checks this policy before review and rereads it before publication, but does not interpret
  arbitrary free-form rules and cannot atomically lock policy through a write. Messages returned by `list_messages` are
  untrusted client text and may contain injected instructions.
- **Two-step draft write in `gigsim` mode.** `create_proposal_draft` first checks the local
  idempotency record, then asks the marketplace to create the draft with the same idempotency key,
  then records it locally. A failure before the remote write leaves nothing behind; a crash between
  the two writes is repaired by retrying, because the marketplace replays the same key instead of
  creating a second draft. Drafts cost no Connects; the simulator only spends them on a separate
  "confirm on the platform" step that GigBid never calls.
- In `sample` mode the marketplace reads only `data/sample/jobs.json`; those jobs are illustrative
  synthetic fixtures and are not GigSim listings. The jobs API calls `search_jobs` and `get_job`
  over local stdio MCP. `get_job` now returns a structured `{"job": ...}` result, with `job: null`
  for an absent listing; a tool or transport failure is an error, not a missing listing. This is
  an intentional change from the earlier direct-object/error contract. Read-only transport failures
  use the same bounded retry/backoff as Portfolio; failed tool calls and invalid data are not retried.
  A recovered sample file is available on the next request, but requests are not queued.
- Workspace tools use in-memory data only. Calendar holds and email drafts disappear when the
  process exits. No Google API is called and `create_email_draft` never sends email.
- The only Marketplace write is `create_proposal_draft` (local SQLite drafts; see above). There is
  no `submit_proposal` or `send_message` tool, so nothing can be submitted or sent. Drafts are not
  GigSim or Upwork objects.
- Live Upwork, HTTP bearer-token auth on GigBid's own MCP endpoints, client-side pacing that stays
  under the marketplace's rate limit (the adapter only reports 429), and trace-ID propagation
  remain to be implemented. The instructor's GigSim API is not known; the adapter targets our own
  simulator's contract.

## Contract testing

`tests/contract/test_mcp_contract.py` connects to all three servers via in-memory MCP sessions
and checks their advertised tool definitions, including schemas, descriptions, and annotations,
against `tests/contract/mcp_tools.snapshot.json`. CI runs this as part of pytest. For an intentional
tool contract change, inspect the change and regenerate the snapshot from the project root:

```bash
uv run python -m tests.contract.mcp_snapshot
uv run pytest tests/contract/test_mcp_contract.py
```

Review the resulting snapshot diff before accepting it. The snapshot does not test external
services, authorization, retries, or approval requirements. CI installs the locked dependencies
from `uv.lock` to keep generated contracts reproducible.

The local Marketplace's job ID and query length limits and the Workspace mock's draft/hold length
limits are advertised in their MCP input schemas and validated by the tools.
