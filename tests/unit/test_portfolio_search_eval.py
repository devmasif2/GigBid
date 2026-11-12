import pytest

from evals.runners.run_demo_eval import DEFAULT_DATASET, Dataset
from evals.runners.run_portfolio_search_eval import evaluate


def test_portfolio_search_eval_labels_and_personas(monkeypatch):
    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "lexical")
    dataset = Dataset.model_validate_json(DEFAULT_DATASET.read_bytes())
    result = evaluate(dataset, "test-hash")
    assert result["search_mode"] == "lexical"
    assert result["model"] is None
    assert result["overall"]["queries"] == len(dataset.queries)
    assert sum(group["queries"] for group in result["by_persona"].values()) == len(dataset.queries)
    assert sum(group["queries"] for group in result["by_job_type"].values()) == len(dataset.queries)
    assert result["dataset"]["sha256"] == "test-hash"
    assert all(row["ranked_ids"] for row in result["queries"])


def test_portfolio_search_eval_fails_on_invalid_backend(monkeypatch):
    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "invalid")
    dataset = Dataset.model_validate_json(DEFAULT_DATASET.read_bytes())
    with pytest.raises(ValueError, match="unsupported portfolio search mode"):
        evaluate(dataset, "test-hash")
