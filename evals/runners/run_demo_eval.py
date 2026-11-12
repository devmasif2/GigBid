"""Reproducible, synthetic-only retrieval component evaluation."""

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag.variants.v0_naive import retrieve
from rag.variants.v1_decomposition import retrieve_by_requirements
from rag.variants.v2_hybrid import hybrid_retrieve
from rag.variants.v3_rerank import rerank
from rag.variants.v8_corrective import build_corrective_retrieval_graph

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data/synthetic_retrieval_dev.json"
VARIANTS = ("v0", "v1", "v2", "v3", "v8")
TOKEN = re.compile(r"[\w+#.-]+", re.UNICODE)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    skills: list[str] = Field(min_length=1)


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    job_type: str = Field(min_length=1)
    query: str = Field(min_length=1)
    requirements: list[str] = Field(min_length=1)
    relevant_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "Query":
        if not self.query.strip() or any(not item.strip() for item in self.requirements):
            raise ValueError("queries and requirements must not be blank")
        if len(set(self.relevant_ids)) != len(self.relevant_ids):
            raise ValueError("relevant evidence IDs must be unique")
        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    data_kind: Literal["synthetic"]
    evidence: list[Evidence] = Field(min_length=1)
    queries: list[Query] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "Dataset":
        evidence = {item.id: item for item in self.evidence}
        if len(evidence) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")
        if len({query.id for query in self.queries}) != len(self.queries):
            raise ValueError("query IDs must be unique")
        for query in self.queries:
            for item_id in query.relevant_ids:
                if item_id not in evidence or evidence[item_id].persona != query.persona:
                    raise ValueError(f"{query.id}: unknown or cross-persona relevant evidence")
        return self


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.casefold())


def evidence_text(item: Evidence) -> str:
    return " ".join((item.title, item.content, *item.skills))


class LexicalIndex:
    """Local bag-of-words vectors, not learned semantic embeddings."""

    def __init__(self, evidence: Sequence[Evidence]):
        vocabulary = sorted({term for item in evidence for term in tokens(evidence_text(item))})
        self.vocabulary = vocabulary
        self.items = [
            {**item.model_dump(), "vector": self.embed_query(evidence_text(item))}
            for item in evidence
        ]

    def embed_query(self, query: str) -> list[float]:
        counts = Counter(tokens(query))
        return [float(counts[term]) for term in self.vocabulary]


def lexical_coverage(query: str, text: str) -> float:
    terms = set(tokens(query))
    return len(terms & set(tokens(text))) / len(terms) if terms else 0.0


def retrieve_variant(variant: str, query: Query, index: LexicalIndex) -> list[dict[str, Any]]:
    if variant == "v0":
        return retrieve(query.query, index, k=10)
    if variant == "v1":
        return retrieve_by_requirements(query.requirements, index, k_per_requirement=10, k=10)
    if variant == "v2":
        return hybrid_retrieve(query.query, index, k=10)
    if variant == "v3":
        candidates = hybrid_retrieve(query.query, index, k=10)
        return rerank(query.query, candidates, lexical_coverage, k=10)
    if variant == "v8":
        graph = build_corrective_retrieval_graph(
            lambda text: hybrid_retrieve(text, index, k=10),
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


def retrieval_metrics(ranked_ids: Sequence[str], relevant_ids: Sequence[str]) -> dict[str, float]:
    if not relevant_ids or len(set(relevant_ids)) != len(relevant_ids):
        raise ValueError("relevant IDs must be non-empty and unique")
    if len(set(ranked_ids)) != len(ranked_ids):
        raise ValueError("ranked IDs must be unique")
    relevant = set(relevant_ids)
    recall = len(set(ranked_ids[:5]) & relevant) / len(relevant)
    reciprocal_rank = next(
        (1 / rank for rank, item in enumerate(ranked_ids[:10], 1) if item in relevant), 0.0
    )
    dcg = sum(
        1 / math.log2(rank + 1)
        for rank, item in enumerate(ranked_ids[:10], 1)
        if item in relevant
    )
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(relevant), 10) + 1))
    return {"recall_at_5": recall, "mrr_at_10": reciprocal_rank, "ndcg_at_10": dcg / ideal}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "queries": len(rows),
        **{
            metric: statistics.mean(row[metric] for row in rows)
            for metric in ("recall_at_5", "mrr_at_10", "ndcg_at_10")
        },
        "latency_ms_p50": statistics.median(latencies),
        "latency_ms_p95_nearest_rank": latencies[math.ceil(0.95 * len(latencies)) - 1],
    }


def evaluate(dataset: Dataset, variants: Sequence[str], dataset_sha256: str) -> dict[str, Any]:
    if not variants or len(set(variants)) != len(variants) or set(variants) - set(VARIANTS):
        raise ValueError("select one or more distinct supported variants")
    indexes = {
        persona: LexicalIndex([item for item in dataset.evidence if item.persona == persona])
        for persona in {query.persona for query in dataset.queries}
    }
    results: dict[str, Any] = {}
    for variant in variants:
        rows = []
        for query in dataset.queries:
            start = time.perf_counter()
            ranked = retrieve_variant(variant, query, indexes[query.persona])
            latency = (time.perf_counter() - start) * 1000
            ranked_ids = [item["id"] for item in ranked]
            rows.append({
                "query_id": query.id,
                "persona": query.persona,
                "job_type": query.job_type,
                "ranked_ids": ranked_ids,
                "relevant_ids": query.relevant_ids,
                **retrieval_metrics(ranked_ids, query.relevant_ids),
                "latency_ms": latency,
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
        "dataset": {
            "name": dataset.name,
            "version": dataset.version,
            "data_kind": dataset.data_kind,
            "sha256": dataset_sha256,
            "query_count": len(dataset.queries),
            "evidence_count": len(dataset.evidence),
        },
        "runtime": {"python": sys.version.split()[0]},
        "scope": "synthetic retrieval component smoke evaluation, not the production bid graph",
        "methods": {
            "vectors": "per-persona bag-of-words term-frequency cosine; not learned embeddings",
            "v1": "per-requirement dense retrieval and reciprocal-rank merge",
            "v2": "full-query dense plus BM25 reciprocal-rank fusion",
            "v3": "v2 candidates reranked by lexical query-term coverage, not a cross-encoder",
            "v8": "v2 retrieval with lexical grading and one requirement-based rewrite",
            "latency": "single in-process retrieval call; index construction excluded; includes V8 graph build",
            "mrr_at_10": "reciprocal rank of first relevant item within top 10",
        },
        "not_measured": [
            "production graph decisions", "proposal quality", "judge scores", "human ratings",
            "simulator outcomes", "tokens", "USD costs", "instructor hidden test",
        ],
        "results": results,
    }


def results_table(result: dict[str, Any]) -> str:
    lines = [
        "# Synthetic retrieval component smoke evaluation",
        "",
        "Hand-authored synthetic development data; not a production or hidden-test benchmark.",
        "Retrieval latency is in-process; judge, outcomes and costs were not measured.",
        "",
        "| Variant | Recall@5 | MRR@10 | nDCG@10 | Unsupported claims/proposal | Judge | Reply rate | p95 retrieval (s) | Cost/proposal |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant, data in result["results"].items():
        metrics = data["overall"]
        lines.append(
            f"| {variant.upper()} | {metrics['recall_at_5']:.3f} | {metrics['mrr_at_10']:.3f} "
            f"| {metrics['ndcg_at_10']:.3f} | Not measured | Not measured | Not measured "
            f"| {metrics['latency_ms_p95_nearest_rank'] / 1000:.6f} | Not measured |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--output", type=Path, help="Write JSON to this path instead of stdout")
    parser.add_argument("--table-output", type=Path, help="Also write a Markdown summary table")
    args = parser.parse_args(argv)
    if args.output and args.table_output and args.output.resolve() == args.table_output.resolve():
        parser.error("--table-output must differ from --output")
    raw = args.dataset.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    result = evaluate(dataset, args.variants, hashlib.sha256(raw).hexdigest())
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote synthetic evaluation to {args.output}")
    else:
        print(output, end="")
    if args.table_output:
        args.table_output.parent.mkdir(parents=True, exist_ok=True)
        args.table_output.write_text(results_table(result), encoding="utf-8")
        print(f"Wrote synthetic evaluation table to {args.table_output}", file=sys.stderr)


if __name__ == "__main__":
    main()
