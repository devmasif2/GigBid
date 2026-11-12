import json
from datetime import date

import pytest

from mcp_servers.portfolio.service import Portfolio


@pytest.fixture
def portfolio(tmp_path):
    path = tmp_path / "portfolio.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "case-1",
                    "title": "Analytics dashboard",
                    "type": "case_study",
                    "source": "case-studies/dashboard.md",
                    "date": "2026-01-15",
                    "outcome": None,
                    "project": "Northstar",
                    "skills": ["Python", "SQL"],
                    "content": "Built a Python analytics dashboard with SQL reporting.",
                },
                {
                    "id": "proposal-1",
                    "title": "Reporting proposal",
                    "type": "proposal",
                    "source": "proposals/reporting.md",
                    "date": "2026-02-01",
                    "outcome": "replied",
                    "project": None,
                    "skills": ["SQL"],
                    "content": "I can build a reporting workflow using SQL.",
                },
            ]
        ),
        encoding="utf-8",
    )
    return Portfolio(path)


def test_search_returns_ranked_evidence_and_applies_filters(portfolio):
    results = portfolio.search_evidence(
        "Python dashboard", k=5, filters={"type": "case_study"}
    )

    assert [item.id for item in results] == ["case-1"]
    assert results[0].source == "case-studies/dashboard.md"
    assert results[0].date == date(2026, 1, 15)


def test_skills_are_unique_and_sorted_case_insensitively(portfolio):
    assert portfolio.list_skills() == ["Python", "SQL"]


def test_starter_kit_portfolio_sample_is_searchable_and_marked_synthetic():
    sample = Portfolio()

    results = sample.search_evidence("scikit-learn classification", k=5)

    assert len(results) == 1
    assert results[0].id == "evidence-001"
    assert results[0].freelancer_id == "sample-ai-engineer"
    assert "synthetic" in results[0].source


def test_case_study_lookup_does_not_return_proposal(portfolio):
    assert portfolio.get_case_study("proposal-1") is None


@pytest.mark.parametrize(
    ("requirement", "k", "message"),
    [
        (" ", 5, "requirement must not be empty"),
        ("python", 0, "k must be between 1 and 50"),
        ("python", 51, "k must be between 1 and 50"),
    ],
)
def test_search_rejects_invalid_input(portfolio, requirement, k, message):
    with pytest.raises(ValueError, match=message):
        portfolio.search_evidence(requirement, k)


def test_search_rejects_unknown_filters(portfolio):
    with pytest.raises(ValueError, match="unsupported filter"):
        portfolio.search_evidence("python", filters={"outcome": "won"})


def test_hybrid_search_retrieves_semantic_and_lexical_hits_and_caches(portfolio, monkeypatch):
    calls = []

    def embed(_self, texts):
        calls.append(tuple(texts))
        if len(texts) == 2:
            return [[1.0, 0.0], [0.0, 1.0]]
        return [[1.0, 0.0]]

    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
    monkeypatch.setattr("rag.ollama_embeddings.OllamaEmbeddings.embed", embed)
    results = portfolio.search_evidence("visualization")
    assert [item.id for item in results] == ["case-1"]
    assert results[0].data_kind == "unverified"
    assert all(text.startswith("search_document: ") for text in calls[0])
    assert calls[1] == ("search_query: visualization",)
    portfolio.search_evidence("visualization")
    assert len(calls) == 3  # Corpus once; query once per search.

    filtered = portfolio.search_evidence("SQL", filters={"type": "proposal"})
    assert [item.id for item in filtered] == ["proposal-1"]
    assert len(calls) == 5


def test_hybrid_search_rebuilds_index_when_corpus_changes(portfolio, monkeypatch):
    calls = []

    def embed(_self, texts):
        calls.append(tuple(texts))
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
    monkeypatch.setattr("rag.ollama_embeddings.OllamaEmbeddings.embed", embed)
    portfolio.search_evidence("Python")
    data = json.loads(portfolio.path.read_text())
    data[0]["content"] = "Updated content."
    portfolio.path.write_text(json.dumps(data))
    portfolio.search_evidence("Python")
    assert len(calls) == 4
    assert "Updated content." in calls[2][0]


def test_hybrid_search_does_not_fall_back_on_model_error(portfolio, monkeypatch):
    from rag.ollama_embeddings import EmbeddingServiceError

    def fail(_self, _texts):
        raise EmbeddingServiceError("unavailable")

    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
    monkeypatch.setattr("rag.ollama_embeddings.OllamaEmbeddings.embed", fail)
    with pytest.raises(EmbeddingServiceError):
        portfolio.search_evidence("Python")


def test_search_rejects_unknown_backend(portfolio, monkeypatch):
    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "typo")
    with pytest.raises(ValueError, match="unsupported portfolio search mode"):
        portfolio.search_evidence("Python")


def test_cross_encoder_reranks_candidate_pool_and_preserves_filters(portfolio, monkeypatch):
    class Model:
        def score(self, query, texts):
            assert query == "reporting"
            return [1.0 if "Reporting proposal" in text else 0.0 for text in texts]

    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
    monkeypatch.setenv("GIGBID_PORTFOLIO_RERANK", "cross_encoder")
    monkeypatch.setenv("GIGBID_RERANK_MODEL_PATH", "/local/model")
    monkeypatch.setattr(
        "rag.ollama_embeddings.OllamaEmbeddings.embed",
        lambda _self, texts: [[1.0, 0.0] for _ in texts],
    )
    monkeypatch.setattr("mcp_servers.portfolio.service.get_local_cross_encoder", lambda _: Model())
    assert [item.id for item in portfolio.search_evidence("reporting", k=1)] == ["proposal-1"]
    assert [item.id for item in portfolio.search_evidence(
        "reporting", k=1, filters={"type": "case_study"}
    )] == ["case-1"]


def test_cross_encoder_requires_hybrid_and_fails_closed(portfolio, monkeypatch):
    from rag.cross_encoder import RerankerError

    monkeypatch.setenv("GIGBID_PORTFOLIO_RERANK", "cross_encoder")
    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "lexical")
    with pytest.raises(ValueError, match="requires ollama_hybrid"):
        portfolio.search_evidence("Python")
    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
    monkeypatch.setattr(
        "rag.ollama_embeddings.OllamaEmbeddings.embed",
        lambda _self, texts: [[1.0, 0.0] for _ in texts],
    )

    def fail(_path):
        raise RerankerError("model unavailable")

    monkeypatch.setattr("mcp_servers.portfolio.service.get_local_cross_encoder", fail)
    with pytest.raises(RerankerError, match="model unavailable"):
        portfolio.search_evidence("Python")
