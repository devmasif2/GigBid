# GigBid: Evidence-grounded, human-approved freelancer automation

## Problem and objective

Freelancers lose time deciding which opportunities deserve attention, finding relevant portfolio
evidence, and drafting replies that are both persuasive and truthful. A naive autonomous agent can
make this worse: it may overstate experience, follow instructions hidden in an untrusted job post,
or spend marketplace Connects without a meaningful review step. GigBid was built as a research
prototype for this problem. Its objective is not to automate submission blindly, but to connect
job discovery, portfolio retrieval, risk assessment, proposal drafting, and client conversation
review while keeping external actions behind explicit human approval.

The central research question was whether decomposing retrieval and workflow decisions improves
evidence quality without sacrificing inspectability. The project also asks whether safety controls
can be made visible enough that a reviewer can understand why a draft was produced and what will
happen if it is approved.

## Architecture

GigBid is split into a FastAPI API, a React/Vite web interface, LangGraph workflows, MCP tool
servers, a local marketplace simulator, retrieval components, and a dependency-free saved-search
worker. The Marketplace MCP server exposes typed read and write contracts. Its sample adapter
serves synthetic fixtures, while the `gigsim` adapter talks to the local simulator. Marketplace
writes are idempotent and support dry-run previews; the graph currently uses only the approved
local draft write, not proposal submission or message sending.

The bid graph starts with a budget gate and then runs analyst, risk, and fit branches in parallel.
Their structured handoffs feed decision and pricing nodes, followed by proposal writing, exact-quote
claim verification, sanitization, bounded critique, compliance, and an interrupt-based approval
gate. The conversation graph validates a client message, drafts a response, and pauses for review.
Both workflows carry typed state, redacted execution events, observability data, and conservative
memory fields. Style memory requires repeated edits; outcome memory accepts only normalized
marketplace outcomes.

The interface presents an opportunity inbox, job detail, streamed graph progress, proposal review,
evidence and compliance feedback, local messages, pipeline status, analytics, portfolio search,
onboarding, and settings. Conversation progress is delivered over Server-Sent Events. The
browser stores only demo profile and thread state; it is not a security boundary.

## Retrieval and evidence grounding

The evaluation compares five configurable retrieval variants. V0 is a lexical baseline. V1
decomposes requirements, V2 applies metadata filters, V3 combines lexical and dense ranking, and
V8 adds corrective retrieval. Optional Ollama embeddings and a local cross-encoder support
ablations, but the default remains lexical because it is deterministic and inspectable.

Every evidence item carries provenance, data-kind, skills, and rights-attestation metadata. The
bid path rejects synthetic or unverified evidence at the final real-evidence gate. Draft claims
must use exact quoted evidence references. The verifier removes unsupported lines before critique
instead of allowing the critic to polish an unsupported claim. This is deliberately conservative:
the checker is not semantic entailment and does not prove that a real-world claim is true.

`make eval` regenerates retrieval, simulator risk, simulator outcomes, claim verification, prompt
injection, graph observability, and a rubric-shaped results table. The development set is small and
hand-authored, so its values are smoke-test evidence rather than general performance claims. The
reports preserve missing measurements as `N/A`; judge calibration, Cohen's kappa, blind human
ratings, and provider USD cost are not invented.

## Safety and orchestration decisions

Job posts and client messages are treated as untrusted input. Tool policy uses caller and server
allowlists, and denied calls are logged without raw arguments. Tool failures are explicit: the
system does not fabricate portfolio evidence or silently treat an unavailable marketplace as
healthy. Graph step and token budgets stop runaway local executions with a visible
`needs_attention` state. The critic loop is bounded, and approval supports edit, reject, and
approve locally.

The approval boundary is intentionally redundant. The UI labels drafts as local and not submitted,
the graph interrupts before the draft write, and the MCP contract is dry-run by default. SQLite
idempotency prevents a transport retry from creating a duplicate draft. The conversation flow
never sends a message, even when a user approves the local review. These controls are appropriate
for an assignment prototype, although the stdio server is not an authentication or isolation
boundary.

## Worker and reliability work

The saved-search worker stores schedules and run claims in SQLite. A composite key of
`search_id` and `scheduled_for` makes duplicate worker claims safe. Completed and failed runs are
recorded explicitly, and the next scheduled occurrence advances only after the claim is created.
The worker callback is injected so marketplace access remains a separate concern. This is a local
reliability primitive, not a distributed queue: Redis, multi-process coordination, tenant
isolation, and live scouting are outside the current implementation.

PostgreSQL checkpoint configuration is available for graph persistence and tests cover checkpoint
recreation. That evidence should not be overstated as process-kill recovery or exactly-once live
submission. The API intentionally remains local because it has no secure multi-user
authentication, token encryption, or public deployment boundary.

## Findings and limitations

The main finding is architectural rather than a claim of production performance: explicit
handoffs and visible approval make it possible to inspect evidence, risk, price, critique, and
external-action intent in one review surface. The retrieval reports show strong results on the
synthetic development labels, while the local observability report demonstrates measurable
latency and deterministic token estimates. The claim-verification report shows the intended
before/after behavior on its small fixture set.

The limitations are material. The official instructor GigSim and live Upwork adapter are not
implemented. Browser sign-in and OAuth connection controls are demonstration state. There is no
tenant isolation, hosted deployment, distributed worker, calibrated judge, blind human panel, or
independently labelled corpus. The simulator outcomes are not evidence of real client reply or
hire rates. The correct next research step is an independently labelled dataset, a 30-item
calibration panel, and a secure authentication boundary before any public deployment.

## Engineering process and lessons

The implementation was intentionally incremental. First, the marketplace and portfolio
interfaces were made explicit as ports and typed MCP contracts. That made it possible to test
adapters without coupling graph logic to a particular marketplace. Next, the retrieval and claim
boundary was established before adding proposal polish. This ordering mattered: a polished draft
can make unsupported evidence look trustworthy, whereas verification makes the unsafe state
visible before critique. The graph was then split into parallel analysis branches and a durable
approval checkpoint, followed by SSE progress so the same state is inspectable in the browser.

Several failures shaped the final design. Early UI tests assumed that an approval draft would be
rendered as paragraph text, but the product correctly exposed it as an editable field; the test
was changed to inspect the field value. Streamed LangGraph interrupts arrived as nested arrays,
so the client parser was corrected to flatten interrupt payloads before restoring a draft.
Marketplace and portfolio outages are surfaced as errors rather than replaced with synthetic
success. These examples reinforce a general rule for agent systems: tests should assert the
intended user-visible contract, while parsers should normalize the exact wire shape rather than
relying on a convenient assumption.

The local worker follows the same principle. Scheduling is separated from marketplace access,
and a run claim is persisted before invoking the injected callback. If the callback fails, the
failure is stored and the process raises an explicit error. A retry cannot silently execute the
same scheduled occurrence twice. This is a useful foundation for a distributed queue, but not a
substitute for one. Production deployment would still need authenticated tenants, encrypted
credentials, leases or transactional claiming across processes, metrics, dead-letter recovery,
and a live adapter contract.

The most useful future ablation is not simply another retriever. It should compare the full
decision path: lexical retrieval with verification, hybrid retrieval with verification, and a
single-agent baseline with the same approval policy. Each should be evaluated on independently
labelled evidence, unsupported-claim rate, decision quality, latency, and human preference.
Separating retrieval quality from decision quality will prevent a higher Recall@5 score from being
mistaken for a better or safer proposal.

## Reproducibility

Use the commands in [the reviewer guide](./REVIEWER_GUIDE.md), then run `make eval`. The
architecture, graph diagrams, tool inventory, data card, AI-use disclosure, and generated
evaluation table provide the evidence trail for the submitted prototype.
