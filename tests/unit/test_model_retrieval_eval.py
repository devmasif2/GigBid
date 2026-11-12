import json
import subprocess
import sys

import pytest

from evals.runners.run_demo_eval import DEFAULT_DATASET, VARIANTS, Dataset, Query
from evals.runners.run_model_retrieval_eval import ModelIndex, evaluate, retrieve_model_variant


class FakeEmbedder:
    model = "nomic-embed-text"

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [
            [1.0, 0.1] if "Python" in text else [0.1, 1.0]
            for text in texts
        ]


class FakeScorer:
    def __init__(self):
        self.calls = []

    def score(self, query, texts):
        self.calls.append((query, texts))
        return [float(len(text)) for text in texts]


def test_model_eval_exercises_all_variants_and_isolates_personas():
    dataset = Dataset.model_validate_json(DEFAULT_DATASET.read_bytes())
    embedder = FakeEmbedder()
    scorer = FakeScorer()
    result = evaluate(dataset, "sha", VARIANTS, embedder, scorer, 0.3)
    assert set(result["results"]) == set(VARIANTS)
    assert result["dataset"]["sha256"] == "sha"
    assert "deterministic placeholders" in result["methods"]["v8"]
    assert len(scorer.calls) == len(dataset.queries)
    persona_by_id = {item.id: item.persona for item in dataset.evidence}
    for data in result["results"].values():
        assert data["overall"]["queries"] == len(dataset.queries)
        assert sum(group["queries"] for group in data["by_persona"].values()) == 12
        for row in data["queries"]:
            assert all(persona_by_id[item] == row["persona"] for item in row["ranked_ids"])
            assert all(0 <= row[key] <= 1 for key in ("recall_at_5", "mrr_at_10", "ndcg_at_10"))
    assert all(
        text.startswith("search_document: ") for call in embedder.calls[:3] for text in call
    )
    assert any(call[0].startswith("search_query: ") for call in embedder.calls[3:])


def test_model_eval_rejects_bad_config_before_indexing():
    dataset = Dataset.model_validate_json(DEFAULT_DATASET.read_bytes())
    embedder = FakeEmbedder()
    for variants, scorer, threshold in [
        (["v3"], None, 0.3), (["v0", "v0"], None, 0.3),
        (["v0"], None, float("nan")), (["v0"], None, 1.1),
    ]:
        with pytest.raises(ValueError):
            evaluate(dataset, "sha", variants, embedder, scorer, threshold)
    assert not embedder.calls


def test_v8_refuses_irrelevant_results():
    dataset = Dataset.model_validate_json(DEFAULT_DATASET.read_bytes())
    index = ModelIndex([item for item in dataset.evidence if item.persona == "ml"], FakeEmbedder())
    query = Query(
        id="unknown", persona="ml", job_type="unknown", query="unmatchedword",
        requirements=["otherunmatchedword"], relevant_ids=["ai-rag"],
    )
    assert retrieve_model_variant("v8", query, index, None, 0.3) == []


def test_v3_empty_candidates_do_not_call_reranker():
    dataset = Dataset.model_validate_json(DEFAULT_DATASET.read_bytes())
    index = ModelIndex([item for item in dataset.evidence if item.persona == "ml"], FakeEmbedder())
    query = Query(
        id="unknown", persona="ml", job_type="unknown", query="unmatchedword",
        requirements=["otherunmatchedword"], relevant_ids=["ai-rag"],
    )
    index.embed_query = lambda _: [-1.0, -1.0]
    scorer = FakeScorer()
    assert retrieve_model_variant("v3", query, index, scorer, 0.3) == []
    assert not scorer.calls


def test_cli_validates_v3_model_before_network_and_does_not_write(tmp_path):
    output = tmp_path / "output.json"
    result = subprocess.run(
        [sys.executable, "-m", "evals.runners.run_model_retrieval_eval", "--variants", "v3",
         "--output", str(output)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "--reranker-path is required" in result.stderr
    assert not output.exists()
    assert json.loads(DEFAULT_DATASET.read_text())["data_kind"] == "synthetic"


def test_cli_refuses_to_overwrite_dataset(tmp_path):
    source = tmp_path / "dataset.json"
    original = DEFAULT_DATASET.read_bytes()
    source.write_bytes(original)
    result = subprocess.run(
        [sys.executable, "-m", "evals.runners.run_model_retrieval_eval", "--variants", "v0",
         "--dataset", str(source), "--output", str(source)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "--output must differ" in result.stderr
    assert source.read_bytes() == original
