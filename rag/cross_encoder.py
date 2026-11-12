"""Local-only cross-encoder inference for portfolio candidate reranking."""

import math
from functools import lru_cache
from pathlib import Path
from threading import Lock


class RerankerError(RuntimeError):
    """A local reranker could not be loaded or returned invalid scores."""


class LocalCrossEncoder:
    def __init__(self, model_path: str) -> None:
        path = Path(model_path).expanduser().resolve()
        if not model_path.strip() or not path.is_dir():
            raise RerankerError("Reranker model must be an existing local directory")
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as error:
            raise RerankerError("Install the optional rerank dependencies to use the model") from error
        try:
            self._model = CrossEncoder(
                str(path),
                device="cpu",
                local_files_only=True,
                trust_remote_code=False,
                model_kwargs={"use_safetensors": True},
            )
        except (OSError, ValueError, RuntimeError) as error:
            raise RerankerError("Could not load the local cross-encoder model") from error
        self._lock = Lock()

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not query.strip() or any(not text.strip() for text in texts):
            raise ValueError("Reranker inputs must not be blank")
        if not texts:
            return []
        with self._lock:
            try:
                max_length = self._model.max_seq_length
                if not isinstance(max_length, int) or max_length < 1:
                    raise RerankerError("Reranker model has no valid sequence limit")
                for text in texts:
                    tokens = self._model.tokenizer(
                        query, text, add_special_tokens=True, truncation=False
                    )["input_ids"]
                    if len(tokens) > max_length:
                        raise RerankerError("Reranker input exceeds model sequence limit")
                scores = self._model.predict(
                    [(query, text) for text in texts],
                    batch_size=16,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                ).tolist()
            except (OSError, ValueError, RuntimeError) as error:
                if isinstance(error, RerankerError):
                    raise
                raise RerankerError("Local cross-encoder inference failed") from error
        if (
            not isinstance(scores, list)
            or len(scores) != len(texts)
            or any(
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                for score in scores
            )
        ):
            raise RerankerError("Local cross-encoder returned invalid scores")
        return [float(score) for score in scores]


@lru_cache(maxsize=1)
def get_local_cross_encoder(model_path: str) -> LocalCrossEncoder:
    return LocalCrossEncoder(model_path)
