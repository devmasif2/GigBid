# Synthetic development evaluations

These are component smoke evaluations, **not** the assignment's full benchmark. The hand-authored
data, simulator, heuristics and reference labels were developed in this project, so results are
optimistic and not independent. Do not treat them as real freelancer evidence, instructor test
results, real-world performance, or a justification for deploying a RAG variant.

## Run

From the project root, after `uv sync --extra dev`:

```bash
make eval
```

This writes the component JSON files and `assignment-results-table.md` under `evals/results/`
(ignored by Git):

- `synthetic-retrieval-dev.json`: per-query rankings, labels, macro averages, per-persona and
  per-job-type summaries, dataset SHA-256 and single-run latency.
- `synthetic-retrieval-table.md`: a generated results table with unmeasured fields marked as such.
- `synthetic-simulator-risk.json`: simulator label/prediction records, confusion matrices,
  precision and recall overall and by category, plus recall by scam type.
- `synthetic-simulator-outcomes.json`: isolated simulator proposal events, simulated Connects,
  reply/hire rates, synthetic fair-price comparisons, and per-persona/category breakdowns for
  V0 and V1 component pipelines.
- `synthetic-claim-verification.json`: per-case and per-persona unsupported-claim counts/rates
  before and after the deterministic sanitizer. This is a self-evaluation of the heuristic
  checker, not semantic entailment or independent truth verification. Its claim counts use
  `require_citation=False` so harmless closing prose is not counted as a whole-draft claim.
- `synthetic-prompt-injection.json`: synthetic attack-success and false-positive rates for job
  and client-message triage. The baseline assumes no detector; the defended result exercises
  the current deterministic risk and liaison heuristics.
- `synthetic-graph-observability.json`: local conversation-graph p50/p95 latency and deterministic
  token estimates. Provider cost is explicitly reported as unavailable.
- `assignment-results-table.md`: rubric-shaped results table combining the reproducible retrieval,
  simulator, and claim-verification outputs. Unmeasured judge, human-panel, provider-cost, and
  variant-outcome fields remain `N/A`.

To select variants, provide a different **synthetic** dataset, or choose output paths:

```bash
uv run python -m evals.runners.run_demo_eval --variants v0 v2 \
  --output evals/results/v0-v2.json --table-output evals/results/v0-v2.md
uv run python -m evals.runners.run_simulator_risk_eval --seed 2026 --jobs 500 --clients 40 \
  --threshold 0.7 --output evals/results/risk.json
uv run python -m evals.runners.run_simulator_outcomes --seed 2026 --jobs 150 --clients 40 \
  --selected 100 --output evals/results/outcomes.json
uv run python -m evals.runners.run_claim_verification_eval \
  --output evals/results/claim-verification.json
uv run python -m evals.runners.run_prompt_injection_eval \
  --output evals/results/prompt-injection.json
uv run python -m evals.runners.run_graph_observability_eval \
  --output evals/results/graph-observability.json
```

Without `--output`, each command writes JSON to stdout. Invalid datasets and arguments fail
explicitly. The retrieval runner requires nonempty relevant labels and disallows cross-persona
gold references; it does not support evaluating a no-relevant-evidence query with these metrics.

## Local portfolio search

The actual Portfolio service defaults to lexical matching. To opt in to experimental local
Ollama hybrid search, first install and run Ollama locally, then pull the embedding model:

```bash
ollama pull nomic-embed-text
export GIGBID_PORTFOLIO_SEARCH=ollama_hybrid
export GIGBID_OLLAMA_URL=http://127.0.0.1:11434
export GIGBID_EMBEDDING_MODEL=nomic-embed-text
export GIGBID_MIN_DENSE_SCORE=0.3
```

These are environment variables for the API/MCP process, not automatic `.env` loading. Start
Ollama before the API; no fallback to lexical search occurs on an error. Only loopback HTTP URLs
are accepted, and HTTP proxies are not used; the embedding model should be installed locally.
Nomic queries and documents use their respective search prefixes. The configurable dense cosine
cutoff is an experimental heuristic, not a validated relevance guarantee. Explicit metadata
filters run before retrieval, and evidence provenance and the existing real-only bid gate are
preserved. The index is held in each MCP process only; graph runs start new processes and rebuild
it, so this is not a persistent vector database. Long texts that exceed model context fail rather
than being silently truncated.

Run the same **actual Portfolio search service** on the hand-authored synthetic dev set:

```bash
GIGBID_PORTFOLIO_SEARCH=lexical uv run python -m evals.runners.run_portfolio_search_eval \
  --output evals/results/portfolio-search-lexical.json
GIGBID_PORTFOLIO_SEARCH=ollama_hybrid uv run python -m evals.runners.run_portfolio_search_eval \
  --output evals/results/portfolio-search-ollama.json
```

Each result contains ranked IDs and metrics overall, by persona and job type, plus model and
threshold metadata. These timings include the first corpus embedding for each persona but omit
MCP startup and graph processing; they depend on model warm-up and machine load. The model name
is a mutable local tag, not a pinned digest. These 12 queries and 18 items are not independent
evaluation, do not measure claim accuracy, and cannot establish that the hybrid mode is superior
on real work. The separate `make eval` variants remain lexical stand-ins, including its V3.

### Optional cross-encoder

The hybrid search can rerank a larger candidate pool with a local, real cross-encoder. This
requires the optional Python dependency group and a model downloaded separately. The following
example uses Python 3.11 and a pinned revision of `cross-encoder/ms-marco-MiniLM-L-6-v2`; check
the model's license and suitability before other use. The download fetches public model files,
not portfolio data:

```bash
uv sync --python 3.11 --extra dev --extra rerank
uv run --python 3.11 --extra rerank hf download cross-encoder/ms-marco-MiniLM-L-6-v2 \
  config.json sentence_bert_config.json tokenizer.json tokenizer_config.json \
  special_tokens_map.json vocab.txt model.safetensors \
  --revision 233902d25c440f23af6f7d6e94d2946bac0bee0a \
  --local-dir data/local/ms-marco-MiniLM-L-6-v2
export GIGBID_PORTFOLIO_RERANK=cross_encoder
export GIGBID_RERANK_MODEL_PATH="$PWD/data/local/ms-marco-MiniLM-L-6-v2"
export GIGBID_RERANK_CANDIDATES=20
```

Set `GIGBID_PORTFOLIO_SEARCH=ollama_hybrid` and run the local Ollama embedding service as above.
Run the API with the same Python environment containing the `rerank` extra. Reranking runs on CPU,
loads only local model files (`trust_remote_code=False`, safetensors required), and fails explicitly
if the model is missing, invalid, or the query/candidate pair exceeds the model's sequence limit.
It does not send portfolio text to Hugging Face. Candidate filtering happens first, and the pool is
the greater of the configured candidate count (1–100) and requested `k`. No minimum reranker score
is used; scores only reorder retrieved candidates, so they are not a safety or evidence guarantee.

Compare identical hybrid search with and without the reranker:

```bash
GIGBID_PORTFOLIO_RERANK=none uv run --python 3.11 --extra rerank \
  python -m evals.runners.run_portfolio_search_eval --output evals/results/hybrid.json
GIGBID_PORTFOLIO_RERANK=cross_encoder uv run --python 3.11 --extra rerank \
  python -m evals.runners.run_portfolio_search_eval --output evals/results/cross-encoder.json
```

The runner records the weights SHA-256, model directory name and candidate count; the embedding
model remains identified by a mutable Ollama tag. On one 12-query synthetic run, Recall@5 was
0.972 in both modes and nDCG@10 was 0.983 without reranking versus 0.978 with reranking. The
reranker did not improve this tiny development set; no claim about real-world performance follows.
The timing includes initial model loading in the first query, but excludes MCP startup and the
graph. The model is loaded once per process; graph calls currently start a new MCP process per run.
Model-backed V3 in this service does not make the separate `make eval` V3 a real cross-encoder.

### Synthetic comparison with local models

The separate model runner compares V0, V1, V2, V3 and V8 on the same versioned synthetic queries
using local Ollama embeddings. V0 is dense full-query search; V1 merges requirement searches;
V2 adds BM25; V3 reranks V2 candidates using the local cross-encoder; V8 adds a bounded
corrective graph to V2. V8's relevance grader and rewriter are **lexical/scripted**, not learned
models. V1 and V8 consume the dataset's hand-authored requirements rather than production agent
extraction. V0/V1 retain all dense results, whereas V2/V3/V8 use a configurable cosine cutoff.

With the optional model environment and local Ollama running (see above):

```bash
uv run --python 3.11 --extra rerank python -m evals.runners.run_model_retrieval_eval \
  --reranker-path data/local/ms-marco-MiniLM-L-6-v2 \
  --output evals/results/synthetic-model-retrieval.json
```

Use `--ollama-url`, `--embedding-model`, `--min-dense-score`, `--variants`, or `--dataset` to
change the experiment; the reranker path is required only when V3 is selected. Each persona's
index contains only its own evidence; labels are used only for scoring. The output includes
per-query rankings, metrics by persona and job type, dataset hash, model tag, reranker weight hash,
and per-variant p50/p95. A local Ollama tag may change: its model digest is not recorded.

One local run of the 12-query dataset produced Recall@5 of 0.972, 1.000, 0.972, 0.972 and 0.889
for V0, V1, V2, V3 and V8 respectively. Corresponding nDCG@10 was 0.985, 0.997, 0.983, 0.978
and 0.899. This set was hand-authored for this project and has only six items per persona; V8's
lexical grader can reject relevant semantic matches. These are exploratory component scores, not
proof that a variant will work best on real jobs. Latency is one call per query in fixed variant
order: model loading and index construction are excluded, but query embedding, cross-encoder
inference and V8 graph construction are included. Cold-start, MCP, network deployment and full
graph latencies are not measured. The existing `make eval` continues to use lexical stand-ins.

## Retrieval methodology

The versioned `data/synthetic_retrieval_dev.json` contains 18 fictional evidence items and 12
manually labelled queries across three fictional personas. Each query is evaluated only against
its persona's six items. The same people/code authored examples and labels: no blinded review,
independent annotation, realistic corpus scale, or test split is present. One-query job-type
subgroups and six-item corpora are especially unsuitable for generalization.

- V0 uses per-persona bag-of-words term-frequency vectors and cosine similarity. These are **not**
  learned dense embeddings.
- V1 applies the existing per-requirement reciprocal-rank merge to those vectors.
- V2 applies the existing dense/BM25 reciprocal-rank fusion.
- V3 applies the existing reranking interface to V2 results using lexical term overlap, **not a
  cross-encoder**.
- V8 applies the existing LangGraph corrective loop to V2 using lexical relevance grades, at most
  one rewrite that appends the provided requirements, and rejection when still below threshold.
  These are deterministic placeholders, not model-based graders or rewriters.

Gold IDs are used only for scoring, never passed to the retrievers. Recall@5 is the fraction of
gold IDs in the first five results; MRR@10 is the reciprocal rank of the first gold ID in the
first ten; nDCG@10 uses binary relevance and the ideal ordering of gold IDs. Aggregate scores
are macro means over queries. Per-query ranks and labels are saved for independent checking.
Each query is timed once in process; p50 is the median and p95 is the nearest-rank percentile.
Index construction, I/O, MCP, generation and network calls are excluded, but V8 graph
construction is included. Timings vary with machine and load and are not production p95 latency.

## Simulator risk methodology

The risk runner calls the local synthetic world generator directly, including future-posted jobs,
then compares `assess_risk` scores with the generator's hidden `is_scam` label. A score at least
0.7 is predicted positive, matching the bid graph's default maximum-risk comparison. Labels are
accessed only after assessment; they are not given to the assessor. The `job_only` and
`job_and_client_history` runs are an ablation of this deterministic component, not complete graph
or marketplace evaluations. At this threshold history-only flags score below 0.7, so this ablation
cannot change classifications unless the other risk logic changes. Precision and recall are `null`
when their denominator is zero. Synthetic scam templates overlap with the assessor's explicit
patterns; neither the labels nor measured scores demonstrate real-world scam detection.
The guaranteed-results risk rule was added after inspecting the seed-2026 failures, so that
seed is a development set and its rerun is not independent validation. A second seed changes
generated jobs but uses the same fixed scam templates, so it is also not a realistic held-out test.

## Isolated simulator outcomes

The outcomes runner creates a new in-memory `gigsim_local` app for each strategy and calls its
HTTP API through `httpx.ASGITransport`. It does not use a configured marketplace URL, user
account, MCP server or production bid graph. The confirmation calls are automatically executed
**only inside this isolated synthetic simulator**; they are not user approval and cannot submit
to a real platform. Each run selects the same first 100 visible jobs by API order (or fewer if
there are not enough), skips explicit risks and jobs with under 40% synthetic skill coverage,
and uses the existing analyst, risk assessor, pricing and writer components. Fictional persona
evidence comes from the retrieval dev dataset. V0 and V1 use bag-of-words retrieval to choose up
to three evidence items. Screening answers are scripted hypothetical approaches, not human
responses or validated factual claims.

After confirming simulated drafts, the runner advances the clock by 120 hours and counts reply
and hire events per confirmed synthetic proposal. It reconciles total Connects spent against the
simulator balance and reports per-job records and persona/category summaries. Price-in-band is
measured only on submitted proposals against the simulator's hidden fair band, read after decisions.
The band is generated around the posted budget midpoint and the baseline price is that midpoint,
so a high score here is largely built into the fixture, not evidence of pricing skill. The existing
claim verifier reports unsupported claims it can detect in the generated cover letters only; it
is a limited rule-based verifier, not a complete claim-accuracy measure.

The simulator's deterministic reply model explicitly rewards job-title overlap, stated skills,
answered screening questions and price under a hidden ceiling. It uses proposal IDs for noise, so
comparisons depend on submission order as well as wording. This small, synthetic fixture does not
evaluate real clients, human review, human judge calibration, production latency, marketplace
contracts or the instructor's hidden test. It is not suitable for selecting a deployed pipeline.

## Not measured

These scripts do **not** evaluate the production bid graph, bid/skip F1, fair-price accuracy, claims
per proposal, LLM-judge scores, human preferences, tokens, or USD cost as required on an independently
labelled development set. The simulator-only price and detected-claim measurements above are limited
proxies, not those benchmark metrics. No judge is calibrated and no full production RAG pipeline is selected. The simulated
world's generated outcomes must not be confused with real-world hiring or an instructor hidden
test. Work on a larger independently annotated development corpus, a cross-encoder and actual
end-to-end, simulator and human evaluations remains necessary.
