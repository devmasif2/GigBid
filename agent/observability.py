"""Small dependency-free observability helpers for local graph runs."""

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

_TOKEN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def new_trace_id() -> str:
    return uuid.uuid4().hex


def estimate_tokens(value: Any) -> int:
    """Estimate text tokens deterministically; this is not a provider tokenizer count."""
    if isinstance(value, str):
        return len(_TOKEN.findall(value))
    if isinstance(value, dict):
        return sum(estimate_tokens(key) + estimate_tokens(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return sum(estimate_tokens(item) for item in value)
    return 0


@dataclass
class Span:
    name: str
    started_at: float = field(default_factory=time.perf_counter)
    ended_at: float | None = None
    token_estimate: int = 0

    def finish(self, value: Any = None) -> None:
        self.ended_at = time.perf_counter()
        self.token_estimate = estimate_tokens(value)

    def as_dict(self) -> dict[str, Any]:
        ended = self.ended_at if self.ended_at is not None else time.perf_counter()
        return {
            "name": self.name,
            "latency_ms": round((ended - self.started_at) * 1000, 3),
            "token_estimate": self.token_estimate,
            "cost_usd": None,
        }


@dataclass
class Trace:
    trace_id: str
    started_at: float = field(default_factory=time.perf_counter)
    spans: list[Span] = field(default_factory=list)

    def span(self, name: str) -> Span:
        current = Span(name)
        self.spans.append(current)
        return current

    def finish(self, value: Any = None) -> dict[str, Any]:
        total_ms = (time.perf_counter() - self.started_at) * 1000
        return {
            "trace_id": self.trace_id,
            "latency_ms": round(total_ms, 3),
            "token_estimate": estimate_tokens(value),
            "cost_usd": None,
            "spans": [span.as_dict() for span in self.spans],
        }
