import math
from collections.abc import Callable, Sequence
from typing import Any


def rerank(
    query: str,
    candidates: Sequence[dict[str, Any]],
    score_pair: Callable[[str, str], float],
    k: int = 5,
) -> list[dict[str, Any]]:
    """V3: rerank retrieved candidates with an injected cross-encoder scorer."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if k < 1:
        raise ValueError("k must be positive")

    ranked: list[tuple[float, str, dict[str, Any]]] = []
    for item in candidates:
        item_id = item.get("id")
        text = item.get("content")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("every candidate must have a non-empty ID")
        if not isinstance(text, str):
            raise TypeError(f"candidate {item_id} must have text content")
        score = score_pair(query, text)
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("reranker score must be a finite number")
        ranked.append((float(score), item_id, item))

    ranked.sort(key=lambda result: (-result[0], result[1]))
    return [
        {**item, "rerank_score": score}
        for score, _, item in ranked[:k]
    ]
