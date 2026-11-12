import httpx
import pytest

from rag.ollama_embeddings import EmbeddingServiceError, OllamaEmbeddings


@pytest.mark.parametrize("url", [
    "https://example.com", "http://example.com", "http://127.0.0.1.evil.example",
    "http://user:password@localhost:11434", "http://localhost:11434/path",
])
def test_embeddings_disallow_non_loopback_or_credentialed_urls(url):
    with pytest.raises(ValueError, match="loopback"):
        OllamaEmbeddings(url, "model")


@pytest.mark.parametrize("payload", [
    {}, {"embeddings": []}, {"embeddings": [[0, 0]]},
    {"embeddings": [[True, 1]]}, {"embeddings": [[1, "x"]]},
    {"embeddings": [[1, 2], [1]]},
])
def test_embeddings_reject_invalid_responses(monkeypatch, payload):
    def post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    count = 2 if payload == {"embeddings": [[1, 2], [1]]} else 1
    with pytest.raises(EmbeddingServiceError):
        OllamaEmbeddings("http://127.0.0.1:11434", "model").embed(["text"] * count)


def test_embeddings_fail_explicitly_when_service_unavailable(monkeypatch):
    def post(*args, **kwargs):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(EmbeddingServiceError, match="request failed"):
        OllamaEmbeddings("http://localhost:11434", "model").embed(["text"])


def test_embeddings_use_local_batch_and_disable_truncation(monkeypatch):
    def post(url, **kwargs):
        assert url == "http://127.0.0.1:11434/api/embed"
        assert kwargs["trust_env"] is False
        assert kwargs["json"] == {
            "model": "model", "input": ["first", "second"], "truncate": False,
        }
        return httpx.Response(
            200, json={"embeddings": [[1, 0], [0, 1]]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", post)
    assert OllamaEmbeddings("http://127.0.0.1:11434", "model").embed(
        ["first", "second"]
    ) == [[1, 0], [0, 1]]
