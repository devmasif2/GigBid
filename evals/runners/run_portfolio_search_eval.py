"""Evaluate the actual portfolio search service on the tiny synthetic development set."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from evals.runners.run_demo_eval import DEFAULT_DATASET, Dataset, retrieval_metrics, summarize
from mcp_servers.portfolio.service import Portfolio


def model_weights_sha256(path: Path) -> str:
    with (path / "model.safetensors").open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def evaluate(dataset: Dataset, dataset_sha256: str) -> dict[str, Any]:
    mode = os.environ.get("GIGBID_PORTFOLIO_SEARCH", "lexical")
    if mode not in {"lexical", "ollama_hybrid"}:
        raise ValueError(f"unsupported portfolio search mode: {mode}")
    reranker = os.environ.get("GIGBID_PORTFOLIO_RERANK", "none")
    if reranker not in {"none", "cross_encoder"}:
        raise ValueError(f"unsupported portfolio reranker: {reranker}")
    if reranker == "cross_encoder" and mode != "ollama_hybrid":
        raise ValueError("cross_encoder reranking requires ollama_hybrid search")

    with TemporaryDirectory(prefix="gigbid-search-eval-") as directory:
        portfolios = {}
        for index, persona in enumerate(sorted({query.persona for query in dataset.queries})):
            path = Path(directory) / f"persona-{index}.json"
            items = [
                {
                    "id": item.id,
                    "title": item.title,
                    "type": "case_study",
                    "source": "synthetic evaluation fixture",
                    "skills": item.skills,
                    "content": item.content,
                    "data_kind": "synthetic",
                }
                for item in dataset.evidence if item.persona == persona
            ]
            path.write_text(json.dumps(items), encoding="utf-8")
            portfolios[persona] = Portfolio(path)

        rows = []
        for query in dataset.queries:
            start = time.perf_counter()
            matches = portfolios[query.persona].search_evidence(query.query, k=10)
            elapsed = (time.perf_counter() - start) * 1000
            ids = [item.id for item in matches]
            rows.append({
                "query_id": query.id,
                "persona": query.persona,
                "job_type": query.job_type,
                "ranked_ids": ids,
                "relevant_ids": query.relevant_ids,
                **retrieval_metrics(ids, query.relevant_ids),
                "latency_ms": elapsed,
            })

    return {
        "scope": "synthetic portfolio search component; not a production graph evaluation",
        "dataset": {"name": dataset.name, "version": dataset.version, "sha256": dataset_sha256},
        "search_mode": mode,
        "model": os.environ.get("GIGBID_EMBEDDING_MODEL", "nomic-embed-text")
        if mode == "ollama_hybrid" else None,
        "min_dense_score": float(os.environ.get("GIGBID_MIN_DENSE_SCORE", "0.3"))
        if mode == "ollama_hybrid" else None,
        "reranker": reranker,
        "reranker_model_directory": (
            Path(os.environ["GIGBID_RERANK_MODEL_PATH"]).name
            if reranker == "cross_encoder" else None
        ),
        "reranker_weights_sha256": (
            model_weights_sha256(Path(os.environ["GIGBID_RERANK_MODEL_PATH"]))
            if reranker == "cross_encoder" else None
        ),
        "reranker_candidates": int(os.environ.get("GIGBID_RERANK_CANDIDATES", "20"))
        if reranker == "cross_encoder" else None,
        "latency_scope": (
            "single local service call per query; includes first corpus embedding for each persona, "
            "excludes MCP and graph"
        ),
        "overall": summarize(rows),
        "by_persona": {
            persona: summarize([row for row in rows if row["persona"] == persona])
            for persona in sorted({row["persona"] for row in rows})
        },
        "by_job_type": {
            job_type: summarize([row for row in rows if row["job_type"] == job_type])
            for job_type in sorted({row["job_type"] for row in rows})
        },
        "queries": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    result = evaluate(dataset, hashlib.sha256(raw).hexdigest())
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote synthetic portfolio search evaluation to {args.output}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
