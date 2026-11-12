# GigBid R&D report

## Abstract

GigBid investigates whether decomposed portfolio retrieval and guarded workflow orchestration
can produce safer freelancer proposals than an unstructured drafting flow. The shipped prototype
combines five retrieval variants, parallel fit/risk analysis, exact-quote verification, bounded
critique, compliance checks, and human approval. All local fixtures and simulator results are
synthetic; this report does not claim live marketplace performance.

## Hypothesis and design

The hypothesis was that requirement decomposition plus hybrid ranking would improve evidence
recall and proposal grounding, while verification and approval would reduce unsupported claims.
The evaluation uses a reproducible synthetic development set with persona and job-type labels.
V0 is the lexical baseline; V1 adds requirement decomposition; V2 adds metadata filtering; V3
adds hybrid ranking; V8 adds corrective retrieval. The same deterministic claim checker and
local graph observability runner are used across runs.

The bid graph runs analyst, risk, and fit branches in parallel, then performs decision, pricing,
drafting, verification, critique, compliance, and approval. The conversation graph validates,
drafts, and pauses for review. Marketplace writes are dry-run by default and the current graph
only creates an idempotent local draft after approval.

## Results

Run `make eval` to regenerate the complete results table at
`evals/results/assignment-results-table.md`. It reports Recall@5, nDCG@10, claim rates, local
p95 latency, and available simulator outcomes by variant/persona/job type. The claim-verification
report includes before/after unsupported-claim rates. Risk evaluation reports confusion matrices,
precision, recall, and scam-type recall. Outcome evaluation reports reply/hire rates and fair-band
comparisons for the measured component variants. Graph observability reports local p50/p95
latency and deterministic token estimates.

Judge calibration, Cohen's kappa, blind human pairwise ratings, provider USD cost, and full
variant outcome coverage are explicitly `N/A`; the project does not fabricate those measurements.
The results are component smoke tests over hand-authored data, not an independent benchmark.

## Safety and failure analysis

The most important failure modes are unsupported evidence, prompt injection in job/client text,
marketplace outages, and confusing a local draft with a submitted proposal. Untrusted text is
isolated from tool policy, evidence is required to be explicitly real before bid approval, and
claim verification removes lines without exact citations. API and UI errors are visible; there
are no silent synthetic fallbacks for unavailable marketplace or portfolio services.

The prototype still has material limits: browser sign-in is demo-only, there is no tenant
isolation, the live Upwork adapter and official instructor GigSim are not implemented, and
distributed worker execution is not provided. PostgreSQL checkpoint tests establish persistence
across checkpointer recreation but do not prove process-kill recovery or exactly-once external
submission. These limits prevent a production-readiness claim.

## Shipped choice and next experiment

The shipped default remains lexical retrieval because it is deterministic, inspectable, and
requires no external model service. Ollama hybrid and local cross-encoder modes are opt-in
ablations. The next experiment should use an independently labelled corpus and a calibrated
human panel before selecting a model-backed default. A second priority is a real multi-tenant
auth boundary before any public deployment.
