import math
from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class DenseVectorIndex(Protocol):
    items: Sequence[Mapping[str, Any]]

    def embed_query(self, query: str) -> Sequence[float]: ...


def retrieve(
    query: str, index: DenseVectorIndex, k: int = 5
) -> list[dict[str, Any]]:
    """V0: top-k cosine retrieval over fixed item vectors and the full corpus."""
    if not query.strip():
        raise ValueError("query must not be empty")
    if k < 1:
        raise ValueError("k must be positive")

    query_vector = index.embed_query(query)
    if not query_vector or not all(
        math.isfinite(value) for value in query_vector
    ):
        raise ValueError("query embedding must contain finite values")
    query_norm = math.sqrt(sum(value * value for value in query_vector))

    ranked: list[tuple[float, str, Mapping[str, Any]]] = []
    for item in index.items:
        item_id = item.get("id")
        vector = item.get("vector")
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("every indexed item must have a non-empty ID")
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
            raise TypeError(f"vector for item {item_id} must be a numeric sequence")
        if len(vector) != len(query_vector):
            raise ValueError(f"vector dimension mismatch for item {item_id}")
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
            raise ValueError(f"vector for item {item_id} must contain finite numbers")

        vector_norm = math.sqrt(sum(value * value for value in vector))
        if query_norm == 0 or vector_norm == 0:
            score = 0.0
        else:
            score = sum(
                left * right for left, right in zip(query_vector, vector, strict=True)
            ) / (query_norm * vector_norm)
        ranked.append((score, item_id, item))

    ranked.sort(key=lambda result: (-result[0], result[1]))
    return [
        {
            **{key: value for key, value in item.items() if key != "vector"},
            "score": score,
        }
        for score, _, item in ranked[:k]
    ]
