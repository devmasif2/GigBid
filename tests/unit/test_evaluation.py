import hashlib
import json
import math
import subprocess
import sys

import pytest
from pydantic import ValidationError

from evals.runners.run_claim_verification_eval import (
    DEFAULT_DATASET as CLAIM_DATASET,
)
from evals.runners.run_claim_verification_eval import Dataset as ClaimDataset
from evals.runners.run_claim_verification_eval import evaluate as evaluate_claims
from evals.runners.run_demo_eval import (
    DEFAULT_DATASET,
    VARIANTS,
    Dataset,
    LexicalIndex,
    Query,
    evaluate,
    retrieval_metrics,
    retrieve_variant,
)
from evals.runners.run_simulator_risk_eval import classification_metrics
from evals.runners.run_simulator_risk_eval import evaluate as evaluate_risk


def test_retrieval_metrics_use_correct_cutoffs_and_binary_dcg():
    relevant = ["a", "b", "c"]
    ranking = ["x", "a", "y", "b", "z", "c"]
    result = retrieval_metrics(ranking, relevant)
    expected_dcg = 1 / math.log2(3) + 1 / math.log2(5) + 1 / math.log2(7)
    ideal_dcg = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert result["recall_at_5"] == pytest.approx(2 / 3)
    assert result["mrr_at_10"] == pytest.approx(1 / 2)
    assert result["ndcg_at_10"] == pytest.approx(expected_dcg / ideal_dcg)
    assert retrieval_metrics([], relevant) == {
        "recall_at_5": 0.0, "mrr_at_10": 0.0, "ndcg_at_10": 0.0
    }
    assert retrieval_metrics([f"x{i}" for i in range(10)] + ["a"], relevant)[
        "mrr_at_10"
    ] == 0
    with pytest.raises(ValueError):
        retrieval_metrics(["a", "a"], relevant)
    with pytest.raises(ValueError):
        retrieval_metrics(["a"], [])


def test_classification_metrics_handle_undefined_denominators():
    assert classification_metrics([True, True, False, False], [True, False, True, False]) == {
        "count": 4,
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 1,
        "precision": 0.5,
        "recall": 0.5,
    }
    assert classification_metrics([False], [False])["precision"] is None
    assert classification_metrics([False], [False])["recall"] is None
    with pytest.raises(ValueError):
        classification_metrics([True], [])


def test_dataset_rejects_leakage_and_invalid_gold():
    data = json.loads(DEFAULT_DATASET.read_text(encoding="utf-8"))
    data["queries"][0]["relevant_ids"] = ["web-dashboard"]
    with pytest.raises(ValidationError, match="cross-persona"):
        Dataset.model_validate(data)
    data["queries"][0]["relevant_ids"] = ["ai-rag", "ai-rag"]
    with pytest.raises(ValidationError, match="unique"):
        Dataset.model_validate(data)
    data["data_kind"] = "real"
    with pytest.raises(ValidationError):
        Dataset.model_validate(data)


def test_all_variants_run_with_persona_isolation_and_repeatable_rankings():
    raw = DEFAULT_DATASET.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    digest = hashlib.sha256(raw).hexdigest()
    first = evaluate(dataset, VARIANTS, digest)
    second = evaluate(dataset, VARIANTS, digest)
    assert first["dataset"]["query_count"] == 12
    assert first["dataset"]["sha256"] == digest
    assert "production graph decisions" in first["not_measured"]
    evidence_by_id = {item.id: item for item in dataset.evidence}
    for variant in VARIANTS:
        rows = first["results"][variant]["queries"]
        second_rows = second["results"][variant]["queries"]
        assert len(rows) == 12
        for row, repeat in zip(rows, second_rows, strict=True):
            assert row["ranked_ids"] == repeat["ranked_ids"]
            assert all(evidence_by_id[item].persona == row["persona"] for item in row["ranked_ids"])
            assert all(0 <= row[metric] <= 1 for metric in ("recall_at_5", "mrr_at_10", "ndcg_at_10"))
        assert sum(group["queries"] for group in first["results"][variant]["by_persona"].values()) == 12


def test_v8_refuses_irrelevant_evidence():
    dataset = Dataset.model_validate_json(DEFAULT_DATASET.read_bytes())
    index = LexicalIndex([item for item in dataset.evidence if item.persona == "ml"])
    query = Query(
        id="unknown", persona="ml", job_type="unknown", query="unmatchedword",
        requirements=["otherunmatchedword"], relevant_ids=["ai-rag"],
    )
    assert retrieve_variant("v8", query, index) == []


def test_simulator_risk_is_reproducible_and_reports_subgroup_counts():
    first = evaluate_risk(12, 100, 10, 0.7)
    assert first == evaluate_risk(12, 100, 10, 0.7)
    for mode in first["modes"].values():
        overall = mode["overall"]
        assert overall["count"] == 100
        assert sum(overall[key] for key in (
            "true_positive", "false_positive", "false_negative", "true_negative"
        )) == 100
        assert sum(group["count"] for group in mode["by_category"].values()) == 100
    with pytest.raises(ValueError):
        evaluate_risk(12, 100, 10, float("nan"))


def test_cli_writes_selected_results_and_fails_on_invalid_dataset(tmp_path):
    output = tmp_path / "nested" / "results.json"
    table = tmp_path / "nested" / "results.md"
    subprocess.run(
        [sys.executable, "-m", "evals.runners.run_demo_eval", "--variants", "v0", "v2",
         "--output", str(output), "--table-output", str(table)],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(output.read_text())
    assert set(result["results"]) == {"v0", "v2"}
    assert "| V0 |" in table.read_text()
    assert "Not measured" in table.read_text()
    bad = tmp_path / "invalid.json"
    bad.write_text('{"data_kind": "real"}')
    failed = subprocess.run(
        [sys.executable, "-m", "evals.runners.run_demo_eval", "--dataset", str(bad)],
        check=False, capture_output=True, text=True,
    )
    assert failed.returncode != 0
    assert "ValidationError" in failed.stderr


def test_risk_cli_and_output_collision(tmp_path):
    output = tmp_path / "risk.json"
    subprocess.run(
        [sys.executable, "-m", "evals.runners.run_simulator_risk_eval",
         "--jobs", "40", "--clients", "5", "--output", str(output)],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(output.read_text())
    assert result["modes"]["job_only"]["overall"]["count"] == 40
    before = output.read_text()
    collision = subprocess.run(
        [sys.executable, "-m", "evals.runners.run_demo_eval",
         "--output", str(output), "--table-output", str(output)],
        check=False, capture_output=True, text=True,
    )
    assert collision.returncode != 0
    assert output.read_text() == before


def test_claim_evaluation_reports_sanitization_effect_by_persona():
    raw = CLAIM_DATASET.read_bytes()
    dataset = ClaimDataset.model_validate_json(raw)
    result = evaluate_claims(dataset, hashlib.sha256(raw).hexdigest())

    assert result["dataset"]["case_count"] == 6
    assert result["overall"]["before"]["unsupported_claims_per_proposal"] > 0
    assert result["overall"]["after"]["unsupported_claims_per_proposal"] == 0
    assert set(result["by_persona"]) == {"data", "ml", "web"}
    assert all(case["after"]["unsupported_claims"] == 0 for case in result["cases"])


def test_claim_dataset_rejects_non_synthetic_or_duplicate_cases():
    data = json.loads(CLAIM_DATASET.read_text(encoding="utf-8"))
    data["data_kind"] = "real"
    with pytest.raises(ValidationError, match="synthetic"):
        ClaimDataset.model_validate(data)
    data["data_kind"] = "synthetic"
    data["cases"].append(data["cases"][0])
    with pytest.raises(ValidationError, match="unique"):
        ClaimDataset.model_validate(data)
