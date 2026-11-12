from agent.observability import Trace, estimate_tokens


def test_token_estimate_is_deterministic_and_not_provider_claim():
    assert estimate_tokens("Build Python dashboards.") == 4
    assert estimate_tokens({"text": "one two", "items": ["three"]}) == 5


def test_trace_records_latency_tokens_and_unknown_cost():
    trace = Trace("trace-1")
    span = trace.span("graph.update")
    span.finish({"message": "hello world"})
    result = trace.finish({"answer": "done"})
    assert result["trace_id"] == "trace-1"
    assert result["token_estimate"] == 2
    assert result["cost_usd"] is None
    assert result["spans"][0]["name"] == "graph.update"
    assert result["spans"][0]["token_estimate"] == 3
    assert result["spans"][0]["latency_ms"] >= 0
