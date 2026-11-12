import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from rag.variants.v0_naive import DenseVectorIndex, retrieve

_TOKEN = re.compile(r"[\w+#.-]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def _item_text(item: Mapping[str, Any]) -> str:
    skills = item.get("skills", [])
    if not isinstance(skills, list):
        skills = []
    return " ".join(
        [
            str(item.get("title", "")),
            str(item.get("content", "")),
            *(str(skill) for skill in skills),
        ]
    )


def bm25_retrieve(
    query: str,
    items: Sequence[Mapping[str, Any]],
    k: int = 5,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query must not be empty")
    if k < 1:
        raise ValueError("k must be positive")
    if k1 <= 0 or not 0 <= b <= 1:
        raise ValueError("BM25 parameters require k1 > 0 and b in [0, 1]")

    query_terms = set(_tokens(query))
    tokenized = [_tokens(_item_text(item)) for item in items]
    document_frequency = Counter(
        term for terms in tokenized for term in set(terms)
    )
    average_length = (
        sum(len(terms) for terms in tokenized) / len(tokenized) if tokenized else 0
    )
    document_count = len(tokenized)
    ranked: list[tuple[float, str, Mapping[str, Any]]] = []

    for item, terms in zip(items, tokenized, strict=True):
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("every indexed item must have a non-empty ID")
        frequencies = Counter(terms)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            inverse_frequency = math.log(
                1
                + (document_count - document_frequency[term] + 0.5)
                / (document_frequency[term] + 0.5)
            )
            length_norm = (
                1 - b + b * len(terms) / average_length
                if average_length
                else 1
            )
            score += (
                inverse_frequency
                * frequency
                * (k1 + 1)
                / (frequency + k1 * length_norm)
            )
        ranked.append((score, item_id, item))

    ranked.sort(key=lambda result: (-result[0], result[1]))
    return [
        {**item, "score": score}
        for score, _, item in ranked[:k]
        if score > 0
    ]


def hybrid_retrieve(
    query: str,
    index: DenseVectorIndex,
    k: int = 5,
    rrf_constant: int = 60,
    *,
    min_dense_score: float | None = None,
) -> list[dict[str, Any]]:
    """V2: reciprocal-rank fusion of dense and BM25 rankings."""
    if rrf_constant < 1:
        raise ValueError("rrf_constant must be positive")
    if min_dense_score is not None and (
        not math.isfinite(min_dense_score) or not -1 <= min_dense_score <= 1
    ):
        raise ValueError("min_dense_score must be finite and between -1 and 1")
    dense = retrieve(query, index, k=max(k, len(index.items)))
    if min_dense_score is not None:
        dense = [item for item in dense if item["score"] >= min_dense_score]
    sparse = bm25_retrieve(query, index.items, k=max(k, len(index.items)))
    merged: dict[str, dict[str, Any]] = {}
    for ranking in (dense, sparse):
        for rank, item in enumerate(ranking, start=1):
            entry = merged.setdefault(item["id"], {**item, "score": 0.0})
            entry["score"] += 1 / (rrf_constant + rank)
    ranked = sorted(merged.values(), key=lambda item: (-item["score"], item["id"]))
    return ranked[:k]
