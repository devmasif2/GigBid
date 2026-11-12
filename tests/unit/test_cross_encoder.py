import os

import pytest

from rag.cross_encoder import LocalCrossEncoder, RerankerError


def test_missing_local_model_is_explicit(tmp_path):
    with pytest.raises(RerankerError, match="existing local directory"):
        LocalCrossEncoder(str(tmp_path / "missing"))


class FakeModel:
    max_seq_length = 4

    def tokenizer(self, query, text, **kwargs):
        assert kwargs["truncation"] is False
        return {"input_ids": (query + " " + text).split()}

    def predict(self, pairs, **kwargs):
        class Values:
            def tolist(self):
                return [float(len(text)) for _, text in pairs]

        assert kwargs["batch_size"] == 16
        return Values()


@pytest.fixture
def scorer():
    from threading import Lock

    instance = LocalCrossEncoder.__new__(LocalCrossEncoder)
    instance._model = FakeModel()
    instance._lock = Lock()
    return instance


def test_cross_encoder_batches_and_rejects_long_inputs(scorer):
    assert scorer.score("query", ["short", "longer"]) == [5, 6]
    with pytest.raises(RerankerError, match="exceeds"):
        scorer.score("one two", ["three four five"])
    assert scorer.score("query", []) == []


@pytest.mark.parametrize("scores", [[float("nan")], [True], [], [[0.1]], [float("inf")]])
def test_cross_encoder_rejects_invalid_scores(scorer, scores):
    class Values:
        def tolist(self):
            return scores

    scorer._model.predict = lambda *_args, **_kwargs: Values()
    with pytest.raises(RerankerError, match="invalid scores"):
        scorer.score("query", ["text"])


def test_real_local_model_when_explicitly_configured():
    path = os.environ.get("GIGBID_TEST_RERANK_MODEL")
    if not path:
        pytest.skip("Set GIGBID_TEST_RERANK_MODEL to run local model integration")
    scorer = LocalCrossEncoder(path)
    scores = scorer.score("Python reporting", [
        "Built a Python reporting dashboard.", "Painted a fence.",
    ])
    assert len(scores) == 2
    assert scores[0] > scores[1]
