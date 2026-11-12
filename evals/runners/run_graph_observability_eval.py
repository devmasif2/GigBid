"""Measure local conversation-graph latency and deterministic usage estimates."""

import argparse
import asyncio
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from agent.graphs.conversation_graph import build_conversation_graph
from agent.observability import Trace

DEFAULT_MESSAGES = (
    "Could you clarify the project scope?",
    "Could you share your availability for an interview?",
    "Is the budget flexible for this work?",
    "Thank you for the update.",
)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    return values[math.ceil(percentile * len(values)) - 1]


async def _evaluate(messages: tuple[str, ...], repetitions: int) -> list[dict[str, Any]]:
    rows = []
    for index in range(repetitions):
        message = messages[index % len(messages)]
        trace = Trace(f"local-eval-{index}")
        span = trace.span("conversation.graph")
        started = time.perf_counter()
        graph = build_conversation_graph()
        result = await graph.ainvoke(
            {
                "conversation_id": f"eval-{index}",
                "client_message": message,
                "available_slots": ["Monday 10:00 UTC"],
            },
            config={"configurable": {"thread_id": f"eval-{index}"}},
        )
        span.finish(result)
        summary = trace.finish(result)
        summary["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        rows.append(summary)
    return rows


def evaluate(repetitions: int = 20) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    rows = asyncio.run(_evaluate(DEFAULT_MESSAGES, repetitions))
    latencies = sorted(row["latency_ms"] for row in rows)
    return {
        "scope": (
            "local deterministic conversation graph measurement; excludes API and MCP startup "
            "and does not represent provider billing"
        ),
        "runtime": {"python": sys.version.split()[0]},
        "repetitions": repetitions,
        "metrics": {
            "latency_ms_p50": statistics.median(latencies),
            "latency_ms_p95": _percentile(latencies, 0.95),
            "token_estimate_per_run_p50": statistics.median(
                row["token_estimate"] for row in rows
            ),
            "cost_usd_per_run": None,
        },
        "runs": rows,
        "not_measured": [
            "provider token counts",
            "provider USD cost",
            "API/network/MCP startup latency",
            "production load p95",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.repetitions)
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote graph observability evaluation to {args.output}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
