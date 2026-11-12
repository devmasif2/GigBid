"""Compare retrieval components with local model embeddings on synthetic development data."""

import argparse
import hashlib
import json
import math
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from evals.runners.run_demo_eval import (
    DEFAULT_DATASET,
    VARIANTS,
    Dataset,
    Evidence,
    Query,
    evidence_text,
    lexical_coverage,
    retrieval_metrics,
    summarize,
)
from evals.runners.run_portfolio_search_eval import model_weights_sha256
from rag.cross_encoder import LocalCrossEncoder
from rag.ollama_embeddings import OllamaEmbeddings
from rag.variants.v0_naive import retrieve
from rag.variants.v1_decomposition import retrieve_by_requirements
from rag.variants.v2_hybrid import hybrid_retrieve
from rag.variants.v3_rerank import rerank
from rag.variants.v8_corrective import build_corrective_retrieval_graph


class ModelIndex:
    def __init__(self, evidence: Sequence[Evidence], embedder: OllamaEmbeddings) -> None:
        self.embedder = embedder
        self.is_nomic = embedder.model.split(":", 1)[0] == "nomic-embed-text"
        prefix = "search_document: " if self.is_nomic else ""
        vectors = embedder.embed([prefix + evidence_text(item) for item in evidence])
        self.items = [
            {**item.model_dump(), "vector": vector}
            for item, vector in zip(evidence, vectors, strict=True)
        ]

    def embed_query(self, query: str) -> list[float]:
        prefix = "search_query: " if self.is_nomic else ""
        return self.embedder.embed([prefix + query])[0]


def retrieve_model_variant(
    variant: str,
    query: Query,
    index: ModelIndex,
    scorer: LocalCrossEncoder | None,
    minimum_dense_score: float,
) -> list[dict[str, Any]]:
    if variant == "v0":
        return retrieve(query.query, index, k=10)
    if variant == "v1":
        return retrieve_by_requirements(query.requirements, index, k_per_requirement=10, k=10)
    if variant == "v2":
        return hybrid_retrieve(query.query, index, k=10, min_dense_score=minimum_dense_score)
    if variant == "v3":
        if scorer is None:
            raise ValueError("v3 requires a local cross-encoder")
        candidates = hybrid_retrieve(
            query.query, index, k=10, min_dense_score=minimum_dense_score
        )
        if not candidates:
            return []
        texts = [" ".join((item["title"], item["content"], *item["skills"])) for item in candidates]
        scores = scorer.score(query.query, texts)
        if len(scores) != len(candidates):
            raise ValueError("reranker returned an invalid score count")
        scored = [{**item, "content": text} for item, text in zip(candidates, texts, strict=True)]
        scores_by_text = dict(zip(texts, scores, strict=True))
        return rerank(query.query, scored, lambda _, text: scores_by_text[text], k=10)
    if variant == "v8":
        graph = build_corrective_retrieval_graph(
            lambda text: hybrid_retrieve(
                text, index, k=10, min_dense_score=minimum_dense_score
            ),
            lambda text, items: {
                "scores": [lexical_coverage(text, item["content"]) for item in items],
                "feedback": "Add the stated requirements.",
            },
            lambda text, *_: f"{text} {' '.join(query.requirements)}",
            max_attempts=1,
            minimum_relevance=0.1,
        )
        result = graph.invoke({"query": query.query})
        return result["evidence"] if result["accepted"] else []
    raise ValueError(f"unknown variant: {variant}")


def evaluate(
    dataset: Dataset,
    dataset_sha256: str,
    variants: Sequence[str],
    embedder: OllamaEmbeddings,
    scorer: LocalCrossEncoder | None,
    minimum_dense_score: float,
) -> dict[str, Any]:
    if not variants or len(set(variants)) != len(variants) or set(variants) - set(VARIANTS):
        raise ValueError("select one or more distinct supported variants")
    if "v3" in variants and scorer is None:
        raise ValueError("v3 requires a local cross-encoder")
    if not math.isfinite(minimum_dense_score) or not -1 <= minimum_dense_score <= 1:
        raise ValueError("min_dense_score must be finite and between -1 and 1")
    indexes = {
        persona: ModelIndex([item for item in dataset.evidence if item.persona == persona], embedder)
        for persona in sorted({query.persona for query in dataset.queries})
    }
    results: dict[str, Any] = {}
    for variant in variants:
        rows = []
        for query in dataset.queries:
            start = time.perf_counter()
            ranked = retrieve_model_variant(
                variant, query, indexes[query.persona], scorer, minimum_dense_score
            )
            elapsed = (time.perf_counter() - start) * 1000
            ranked_ids = [item["id"] for item in ranked]
            rows.append({
                "query_id": query.id,
                "persona": query.persona,
                "job_type": query.job_type,
                "ranked_ids": ranked_ids,
                "relevant_ids": query.relevant_ids,
                **retrieval_metrics(ranked_ids, query.relevant_ids),
                "latency_ms": elapsed,
            })
        results[variant] = {
            "overall": summarize(rows),
            "by_persona": {
                name: summarize([row for row in rows if row["persona"] == name])
                for name in sorted({row["persona"] for row in rows})
            },
            "by_job_type": {
                name: summarize([row for row in rows if row["job_type"] == name])
                for name in sorted({row["job_type"] for row in rows})
            },
            "queries": rows,
        }
    return {
        "scope": "synthetic component comparison, not production graph or instructor benchmark",
        "dataset": {
            "name": dataset.name, "version": dataset.version, "data_kind": dataset.data_kind,
            "sha256": dataset_sha256, "query_count": len(dataset.queries),
            "evidence_count": len(dataset.evidence),
        },
        "runtime": {"python": sys.version.split()[0]},
        "embedding_model": embedder.model,
        "embedding_model_identity": "local Ollama tag; digest not recorded",
        "min_dense_score": minimum_dense_score,
        "methods": {
            "v0": "full-query dense cosine",
            "v1": "per-requirement dense cosine with reciprocal-rank merge",
            "v2": "full-query dense and BM25 reciprocal-rank fusion",
            "v3": "v2 candidates reranked by local cross-encoder",
            "v8": "v2 with lexical grading and at most one requirement-based rewrite; "
                  "grader and rewriter are deterministic placeholders",
            "timing": "one query per variant; index construction and model loading excluded, "
                      "Ollama queries and V8 graph build included; no warmup or randomization",
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--reranker-path", type=Path)
    parser.add_argument("--min-dense-score", type=float, default=0.3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if "v3" in args.variants and args.reranker_path is None:
        parser.error("--reranker-path is required for v3")
    if args.output and args.output.resolve() == args.dataset.resolve():
        parser.error("--output must differ from --dataset")
    raw = args.dataset.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    embedder = OllamaEmbeddings(args.ollama_url, args.embedding_model)
    scorer = LocalCrossEncoder(str(args.reranker_path)) if "v3" in args.variants else None
    result = evaluate(
        dataset, hashlib.sha256(raw).hexdigest(), args.variants, embedder, scorer,
        args.min_dense_score,
    )
    result["reranker"] = (
        {"directory": args.reranker_path.name,
         "weights_sha256": model_weights_sha256(args.reranker_path)}
        if args.reranker_path is not None and scorer is not None else None
    )
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote synthetic model retrieval evaluation to {args.output}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
