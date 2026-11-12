import pytest

from rag.variants.v0_naive import retrieve
from rag.variants.v1_decomposition import retrieve_by_requirements
from rag.variants.v2_hybrid import bm25_retrieve, hybrid_retrieve
from rag.variants.v3_rerank import rerank
from rag.variants.v8_corrective import build_corrective_retrieval_graph


class FixtureIndex:
    def __init__(self):
        self.items = [
            {
                "id": "multi",
                "title": "Python and SQL",
                "content": "Python and SQL reporting project.",
                "skills": ["Python", "SQL"],
                "vector": [0.8, 0.8],
            },
            {
                "id": "python",
                "title": "Python analysis",
                "content": "Python analysis work.",
                "skills": ["Python"],
                "vector": [1.0, 0.0],
            },
            {
                "id": "postgres",
                "title": "PostgreSQL reporting",
                "content": "Use PostgreSQL to generate reports.",
                "skills": ["PostgreSQL"],
                "vector": [0.0, 1.0],
            },
        ]

    def embed_query(self, query: str) -> list[float]:
        if "postgres" in query.casefold() or "sql" in query.casefold():
            return [0.0, 1.0]
        return [1.0, 0.0]


def test_v0_ranks_with_cosine_and_omits_raw_vectors():
    results = retrieve("Python", FixtureIndex(), k=3)

    assert [item["id"] for item in results] == ["python", "multi", "postgres"]
    assert all("vector" not in item for item in results)
    assert results[0]["score"] == pytest.approx(1.0)


def test_v0_rejects_bad_query_and_dimension_mismatch():
    with pytest.raises(ValueError, match="query must not be empty"):
        retrieve(" ", FixtureIndex())

    class BadIndex(FixtureIndex):
        def __init__(self):
            super().__init__()
            self.items = [{"id": "wrong-dim", "vector": [1.0]}]

    with pytest.raises(ValueError, match="dimension mismatch"):
        retrieve("Python", BadIndex())


def test_v1_merges_requirement_rankings_and_tracks_coverage():
    results = retrieve_by_requirements(
        ["Python", "SQL"], FixtureIndex(), k_per_requirement=3, k=3
    )

    multi_requirement_result = next(
        result for result in results if result["id"] == "multi"
    )
    assert multi_requirement_result["matched_requirements"] == ["Python", "SQL"]


def test_bm25_retrieves_exact_skill_names_and_rrf_combines_rankings():
    index = FixtureIndex()

    sparse = bm25_retrieve("PostgreSQL", index.items, k=2)
    hybrid = hybrid_retrieve("PostgreSQL", index, k=3)

    assert sparse[0]["id"] == "postgres"
    assert hybrid[0]["id"] == "postgres"
    assert hybrid[0]["score"] > 0


def test_hybrid_dense_cutoff_keeps_sparse_hits_and_preserves_default():
    index = FixtureIndex()
    default = hybrid_retrieve("Python", index, k=3)
    filtered = hybrid_retrieve("Python", index, k=3, min_dense_score=0.9)
    assert {item["id"] for item in default} == {"multi", "python", "postgres"}
    assert {item["id"] for item in filtered} == {"multi", "python"}
    with pytest.raises(ValueError, match="min_dense_score"):
        hybrid_retrieve("Python", index, min_dense_score=float("nan"))


def test_v3_uses_injected_pair_scorer_for_order():
    candidates = [
        {"id": "a", "content": "Python only"},
        {"id": "b", "content": "Python and SQL"},
    ]

    results = rerank(
        "Python SQL",
        candidates,
        lambda query, content: 2 if "SQL" in query and "SQL" in content else 1,
        k=1,
    )

    assert results[0]["id"] == "b"
    assert results[0]["rerank_score"] == 2.0


@pytest.mark.parametrize("score", [float("nan"), float("inf"), True])
def test_v3_rejects_invalid_reranker_scores(score):
    with pytest.raises(ValueError, match="finite number"):
        rerank("query", [{"id": "a", "content": "text"}], lambda _q, _t: score)


def test_v8_retries_low_relevance_once_with_rewritten_query():
    retrieved_queries = []

    def retrieve_fn(query):
        retrieved_queries.append(query)
        return [{"id": query, "content": query}]

    def grade_fn(query, evidence):
        score = 0.9 if evidence and "specific" in query else 0.1
        return {"scores": [score], "feedback": "Add the missing skill"}

    graph = build_corrective_retrieval_graph(
        retrieve_fn,
        grade_fn,
        lambda query, evidence, feedback: (
            f"{query} specific" if evidence and feedback else query
        ),
        max_attempts=2,
    )

    result = graph.invoke({"query": "broad project", "attempts": 0})

    assert result["accepted"] is True
    assert result["attempts"] == 1
    assert retrieved_queries == ["broad project", "broad project specific"]


def test_v8_stops_after_retry_budget_and_validates_relevance_scores():
    graph = build_corrective_retrieval_graph(
        lambda query: [{"id": query, "content": f"not relevant to {query}"}],
        lambda query, evidence: {
            "scores": [
                0.1
                if any(term in item["content"].lower() for term in query.lower().split())
                else 0.0
                for item in evidence
            ],
            "feedback": "Try again",
        },
        lambda query, evidence, feedback: (
            f"{query} refined" if evidence and feedback else query
        ),
        max_attempts=1,
    )

    result = graph.invoke({"query": "initial"})

    assert result["accepted"] is False
    assert result["attempts"] == 1
    assert result["query"] == "initial refined"

    invalid_graph = build_corrective_retrieval_graph(
        lambda query: [{"id": query}],
        lambda query, evidence: {
            "scores": [1.1 for _ in evidence] if query else []
        },
        lambda query, evidence, feedback: query if evidence or feedback else "",
    )
    with pytest.raises(ValueError, match="between 0 and 1"):
        invalid_graph.invoke({"query": "initial"})
