from collections.abc import Sequence
from typing import Any

from rag.variants.v0_naive import DenseVectorIndex, retrieve


def retrieve_by_requirements(
    requirements: Sequence[str],
    index: DenseVectorIndex,
    k_per_requirement: int = 5,
    k: int = 5,
) -> list[dict[str, Any]]:
    """V1: retrieve each explicit requirement and merge results by reciprocal rank."""
    if not 1 <= k_per_requirement <= 50 or not 1 <= k <= 50:
        raise ValueError("k and k_per_requirement must be between 1 and 50")

    merged: dict[str, dict[str, Any]] = {}
    for requirement in requirements:
        if not requirement.strip():
            continue
        for rank, result in enumerate(
            retrieve(requirement, index, k_per_requirement), start=1
        ):
            item_id = result["id"]
            entry = merged.setdefault(
                item_id,
                {
                    **result,
                    "score": 0.0,
                    "matched_requirements": [],
                },
            )
            entry["score"] += 1 / rank
            entry["matched_requirements"].append(requirement)

    ranked = sorted(merged.values(), key=lambda item: (-item["score"], item["id"]))
    return ranked[:k]
