# Architecture

## Implemented workflows

```text
Bid graph
  START --> [Job Analyst || Risk Assessor || Fit Matcher]
         --> decision --> price --> writer --> claim verify/sanitize
         --> critic (max two revisions) --> compliance --> interrupt for approval
         --> (approved only) publish local draft via Marketplace MCP --> END

Conversation graph
  START --> validate --> classify and draft --> interrupt for approval --> END
```

The messages panel reads local simulator messages through `GET /messages` and the read-only
Marketplace MCP `list_messages` tool. In sample mode or during an outage it reports unavailable
instead of fabricating messages. Message text is untrusted; the deterministic Client Liaison
identifies some injection and off-platform signals and drafts a conservative response. A client
message can be sent to the conversation graph for local review. Replies can be edited and
rechecked for configured contact, guarantee and off-platform patterns, and for some unsupported
first-person claims and citations. These heuristic checks are incomplete and do not verify all
claims or enforce live marketplace policy. Approval is blocked for failed edits and unsaved browser
changes; reject remains available. None of these actions sends a message or writes to the simulator.
The browser restores one tracked review while its checkpoint exists; unsaved edits are not restored.
Actual sending, Workspace-backed interview scheduling, authentication, and persistent multi-user
review remain unimplemented.

The read-only pipeline panel retrieves simulator proposal stages and Connects through
`GET /pipeline` and the Marketplace MCP `list_proposals` and `get_connects_balance` tools.
The API validates simulator responses and excludes proposal text from its response. The two
reads are sequential, not an atomic snapshot, and require manual refresh; a failure returns
503 rather than partial or fabricated data. Sample mode has no simulator pipeline. Viewing it
does not confirm proposals or spend Connects. Simulator state resets on simulator restart.

The three bid analysis branches use LangGraph `Send` and join before the decision node. The
analyst maps fields already present in a job into a typed `JobSpec`; the risk assessor flags
configured patterns and starter warning signals. In `gigsim` mode it checks the supplied job against
the current listing and reads public client history through Marketplace MCP; unverified payment,
low hire rate, and low rating add explicit heuristic flags. These scores are not calibrated
probabilities. Sample mode has no client history and reports that limitation. The fit matcher compares required skill labels with retrieved portfolio evidence and
returns evidence IDs. Proposal text quotes exact evidence snippets, the verifier checks citations,
and the sanitizer removes identified unsupported lines before the Critic. Verification records
the source line for each detected claim so a modified or malformed quotation is actually removed,
even when another quote uses the same evidence ID. This is a conservative line-based heuristic,
not complete claim splitting or semantic fact verification; it can miss unsupported statements
and exact quotations do not prove truth, authorship, or rights. Human review remains essential.

The bid graph's fit branch launches the local Portfolio MCP server over stdio and calls only
`search_evidence`, once per required skill. It validates returned evidence and preserves its
provenance; transient transport failures are retried up to twice with backoff, while invalid
responses fail immediately. A failed or timed-out MCP request fails the run rather than treating
missing evidence as a successful search. The API reports a 503 for start requests and an SSE error
event for streams. This is a local stdio integration, not yet the required multi-server client with
marketplace reconnection, queueing, or a full per-agent policy. The standalone deterministic `match_fit`
helper still accepts the local service for isolated tests.

The job inbox API also uses the local Marketplace MCP server over stdio for search and details.
Missing jobs produce a structured null result and HTTP 404; transport, tool, or invalid-data
failures produce HTTP 503. It retries only read-only transport failures; it does not queue requests.
Both MCP call paths enforce caller-, server-, and tool-specific allowlists before dispatch. This
client-side policy is not server authentication; other agents and future tool calls still require
their own policy integration.

Portfolio MCP can optionally use local Ollama embeddings plus BM25 reciprocal-rank fusion
(`GIGBID_PORTFOLIO_SEARCH=ollama_hybrid`); lexical matching remains the default. The opt-in mode
only accepts a loopback HTTP endpoint, disables proxy use and truncation, validates embeddings,
and fails explicitly on model/service errors. It filters the corpus before ranking, uses a
configurable cosine threshold for dense candidates, and keeps corpus vectors in process memory
only until that MCP process exits. These settings are experimental, not calibrated for actual
portfolio relevance. Exact skill matching and the real-evidence gate remain in place; retrieval
alone does not verify claims. Each graph retrieval opens a new MCP process, so corpus embeddings
are rebuilt for each run. There is no persistent vector store or shared index.

An optional local manifest-based ingestion CLI builds a complete JSON index from Markdown, text,
and text-based PDF files, preserving declared metadata and content-addressed chunk IDs. It defaults to
git-ignored local storage and requires a rights attestation for evidence declared real; neither
the attestation nor the underlying claims are independently verified. PDF extraction can omit
or reorder content, has no OCR, and requires review. A separate opt-in CLI reads individually
selected README/code files at pinned commits from the official remote GitHub MCP server, with
explicit operator labels and rights attestations. A combined CLI can preview and rebuild a single
index from both manifests, and a read-only API/web panel searches the configured index through
Portfolio MCP. Indexing is still a full rebuild; there is no UI upload, authentication or tenant
isolation. GitHub authorship is not verified, and authenticated GitHub access has not been
live-tested. The local API must not be exposed publicly.

An opt-in single-user document manager accepts local text, Markdown, and text-based PDFs and
stores per-source chunks in SQLite. Creates, replacements, and deletes commit transactionally;
revision checks reject stale writes. Portfolio MCP reads the SQLite corpus when configured.
Raw uploads are not retained, but extracted text and metadata are plaintext. This corpus is
separate from JSON manifest indexes, and uploads do not reindex GitHub sources. Management
requires a loopback client and a locally configured token; these do not protect unauthenticated
search or make the application safe to deploy publicly or through an untrusted proxy.

With `GIGBID_PORTFOLIO_RERANK=cross_encoder`, hybrid candidates can be reordered using a
local Sentence Transformers cross-encoder on CPU. The model path must be a pre-downloaded local
directory; loading is local-only, custom remote code is disabled, and safetensors weights are
required. Query/candidate pairs are scored in batches and inputs beyond the model sequence limit
fail explicitly rather than being silently truncated. Reranking is off by default, preserves
filtered evidence and provenance, and cannot prove that a retrieved claim is true. Each MCP
process loads its own model; inference latency and memory cost need production measurement.

In `gigsim` mode the compliance step reads and validates the current simulator policy and listing
through Marketplace MCP. It checks the cover-letter limit, banned phrases, and required screening
answers in addition to the existing deterministic checks. If missing answers are the only
compliance issue, the graph opens a blocked review so the user can edit them; approval remains
blocked until rechecking passes. The UI supports editing the letter and each answer, and rejects
an incorrect answer count. Edited answers are checked for evidence citations, unsupported
first-person claims, and prohibited text, but the deterministic verifier cannot detect all
unsupported claims and does not replace human review. The review shows the policy version and the
Connects estimate adjusted by its multiplier. Edited text is rechecked against the reviewed
policy. Immediately before draft creation the graph rereads the
policy and listing: a change or adapter-mode switch stops publication and requires a new analysis;
an unavailable service produces an explicit error and no write. These checks are not atomic with
the subsequent write, so they cannot eliminate a race with a concurrent update. The simulator
checks its own rules again on confirmation, which GigBid does not perform. Free-form policy rules
are not automatically interpreted; this is not full policy-pack enforcement.

In sample mode marketplace policy and client history are unavailable. Existing local-only sample
drafts remain available under the illustrative static checks, with the missing policy identified
in the review; they are not evidence of compliance with a real marketplace.

Only evidence explicitly labelled `real` can move a job to the bid path. The starter portfolio is
synthetic, so the local graph returns `watch` instead of drafting a proposal. Approval interrupts
resume by thread ID. Only an `approve` response leads to the `publish_draft` node, which calls the
Marketplace MCP `create_proposal_draft` write (local SQLite draft, idempotent, audited; never a
submission). Reject and needs-attention outcomes end the run without any write. If that write fails
(for example the marketplace is down), the API returns 503 and the checkpointed run stays at the
publish step; `POST /graphs/bid/{thread_id}/continue` resumes it without repeating completed steps,
and the idempotency key prevents a duplicate draft. The current API has no
authentication, uses in-memory checkpoints by default, and is for local development only. It is
not ready for public deployment.

The graph state API exposes saved state and approval interrupts by graph name and thread ID. The
local UI tracks one bid thread in browser storage, restores its pending review after refresh, and
supports approve/reject or edit-and-recheck. The ID is not a security boundary: there is no user
authentication or tenant isolation. In-memory checkpoints disappear on API restart; PostgreSQL
recovery and concurrent exactly-once processing have not been verified. No marketplace write is
performed after approval other than creating a local draft (also mirrored to the local simulator
when configured).

Graph state now keeps three explicit categories separate: current workflow state, an
`execution_trace` containing redacted node observations, and `style_memory`/`outcome_memory`
containing only normalized promoted facts. Repeated user edits require three observations before a
style preference is promoted; raw drafts and tool payloads are never copied into memory. Outcome
memory accepts only normalized `replied`, `hired`, or `lost` events and is not populated from
arbitrary client text.

Both graphs begin with a deterministic step/token budget gate. Defaults are 40 traced steps and
12,000 estimated tokens; callers can provide lower per-thread budgets. Exceeding either budget
ends the run with `approval_status=needs_attention` and a visible reason instead of continuing
unbounded work. The estimates are local heuristics, not provider tokenizer usage.

Both graphs and the API accept an injected checkpointer. The API selects `AsyncPostgresSaver`
when `DATABASE_URL` is configured and creates its tables at startup; otherwise it falls back to
in-memory checkpoints. The local Compose stack runs only the API and PostgreSQL. Checkpoint
history, crash/restart proof, message/proposal writes, and production auth remain outstanding.

The marketplace is one port (`agent/marketplace_port.py`) with adapters selected by configuration:
a static sample adapter and an HTTP adapter for our local simulator
([`gigsim_local`](../gigsim_local/README.md)). The graph and API only see the Marketplace MCP tools,
so switching adapters changes configuration, not graph code. The official Upwork MCP adapter is
not implemented, and no live marketplace action exists. The simulator is our own stand-in rather
than the instructor's GigSim; swapping in the real one should only touch the adapter.
