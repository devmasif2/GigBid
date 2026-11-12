"""Local Ollama embeddings for explicitly configured portfolio search."""

import math
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx


class EmbeddingServiceError(RuntimeError):
    """Local embedding service failed or returned invalid embeddings."""


class OllamaEmbeddings:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        url = urlsplit(base_url)
        if (
            url.scheme != "http"
            or url.hostname not in {"localhost", "127.0.0.1", "::1"}
            or url.username is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError("Ollama URL must be a local loopback HTTP address")
        if not model.strip():
            raise ValueError("Ollama embedding model must not be empty")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("embedding timeout must be positive and finite")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("embedding input must contain non-empty strings")
        try:
            response = httpx.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": list(texts), "truncate": False},
                timeout=self.timeout,
                trust_env=False,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise EmbeddingServiceError("Local Ollama embedding request failed") from error
        vectors = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise EmbeddingServiceError("Local Ollama returned an invalid embedding count")
        dimension = None
        for vector in vectors:
            if (
                not isinstance(vector, list)
                or not vector
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    for value in vector
                )
                or not any(value != 0 for value in vector)
            ):
                raise EmbeddingServiceError("Local Ollama returned an invalid embedding")
            if dimension is None:
                dimension = len(vector)
            elif len(vector) != dimension:
                raise EmbeddingServiceError("Local Ollama returned inconsistent dimensions")
        return vectors
