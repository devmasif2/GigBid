import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent.mcp_client import PortfolioMCPError, retrieve_portfolio_evidence


@pytest.mark.anyio
async def test_hybrid_search_through_stdio_mcp(tmp_path, monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/api/embed"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            vectors = [[1.0, 0.0] for _ in body["input"]]
            response = json.dumps({"embeddings": vectors}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        path = tmp_path / "portfolio.json"
        path.write_text(json.dumps([{
            "id": "fictional", "title": "Synthetic Python project", "type": "case_study",
            "source": "synthetic fixture", "skills": ["Python"], "content": "Built a demo.",
        }]))
        monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
        monkeypatch.setenv("GIGBID_OLLAMA_URL", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv("GIGBID_EMBEDDING_MODEL", "nomic-embed-text")
        results = await retrieve_portfolio_evidence(["Python", "another requirement"], path)
        assert [[item.id for item in result] for result in results] == [
            ["fictional"], ["fictional"]
        ]
        assert all(result[0].data_kind == "synthetic" for result in results)
        assert len(calls) == 3
        assert calls[0]["input"][0].startswith("search_document: ")
        assert calls[1]["input"] == ["search_query: Python"]
        assert calls[2]["input"] == ["search_query: another requirement"]
        assert all(call["truncate"] is False for call in calls)
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.mark.anyio
async def test_hybrid_mcp_does_not_fall_back_when_service_is_down(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_port
    server.server_close()
    monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
    monkeypatch.setenv("GIGBID_OLLAMA_URL", f"http://127.0.0.1:{port}")
    with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
        await retrieve_portfolio_evidence(["scikit-learn"])


@pytest.mark.anyio
async def test_mcp_reranker_error_does_not_fall_back(tmp_path, monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            response = json.dumps({"embeddings": [[1.0, 0.0] for _ in body["input"]]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        monkeypatch.setenv("GIGBID_PORTFOLIO_SEARCH", "ollama_hybrid")
        monkeypatch.setenv("GIGBID_PORTFOLIO_RERANK", "cross_encoder")
        monkeypatch.setenv("GIGBID_RERANK_MODEL_PATH", str(tmp_path / "missing"))
        monkeypatch.setenv("GIGBID_OLLAMA_URL", f"http://127.0.0.1:{server.server_port}")
        with pytest.raises(PortfolioMCPError, match="failed or is unavailable"):
            await retrieve_portfolio_evidence(["scikit-learn"])
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
