"""Evaluate the risk heuristic against labels from the local simulator generator."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agent.nodes.risk_assessor import assess_risk
from gigsim_local.data import generate_world


def classification_metrics(truth: list[bool], predictions: list[bool]) -> dict[str, Any]:
    if not truth or len(truth) != len(predictions):
        raise ValueError("truth and predictions must have the same nonzero length")
    tp = sum(actual and predicted for actual, predicted in zip(truth, predictions, strict=True))
    fp = sum(not actual and predicted for actual, predicted in zip(truth, predictions, strict=True))
    fn = sum(actual and not predicted for actual, predicted in zip(truth, predictions, strict=True))
    tn = len(truth) - tp - fp - fn
    return {
        "count": len(truth),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def evaluate(seed: int, job_count: int, client_count: int, threshold: float) -> dict[str, Any]:
    if job_count < 1 or client_count < 1:
        raise ValueError("job_count and client_count must be positive")
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be in (0, 1]")
    world = generate_world(seed, job_count, client_count)
    modes: dict[str, Any] = {}
    for mode in ("job_only", "job_and_client_history"):
        rows = []
        for job_id, job in sorted(world["jobs"].items()):
            state = {"job": job}
            if mode == "job_and_client_history":
                state["client_history"] = world["clients"][job["client_id"]]["public"]
            report = assess_risk(state)["risk_report"]
            label = world["truth"][job_id]
            rows.append({
                "job_id": job_id,
                "category": job["category"],
                "is_scam": label["is_scam"],
                "scam_kinds": label["scam_kinds"],
                "score": report["score"],
                "flags": report["flags"],
                "predicted_scam": report["score"] >= threshold,
            })

        def summarize(group: list[dict[str, Any]]) -> dict[str, Any]:
            return classification_metrics(
                [row["is_scam"] for row in group], [row["predicted_scam"] for row in group]
            )

        modes[mode] = {
            "overall": summarize(rows),
            "by_category": {
                category: summarize([row for row in rows if row["category"] == category])
                for category in sorted({row["category"] for row in rows})
            },
            "recall_by_scam_kind": {
                kind: {
                    "positive_jobs": len(group),
                    "detected": sum(row["predicted_scam"] for row in group),
                    "recall": sum(row["predicted_scam"] for row in group) / len(group),
                }
                for kind in sorted({kind for row in rows for kind in row["scam_kinds"]})
                for group in [[row for row in rows if kind in row["scam_kinds"]]]
            },
            "jobs": rows,
        }
    return {
        "scope": "synthetic local GigSim stand-in risk component; not a production graph evaluation",
        "generator": "gigsim_local.data.generate_world",
        "seed": seed,
        "runtime": {"python": sys.version.split()[0]},
        "job_count": job_count,
        "client_count": client_count,
        "threshold": threshold,
        "positive_definition": "simulator hidden is_scam label",
        "prediction_definition": "assess_risk score >= threshold; not a calibrated scam probability",
        "population": "all generated jobs, including jobs not yet posted on the simulator clock",
        "modes": modes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--jobs", type=int, default=500)
    parser.add_argument("--clients", type=int, default=40)
    parser.add_argument("--threshold", type=float, default=0.7)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.seed, args.jobs, args.clients, args.threshold)
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote synthetic simulator risk evaluation to {args.output}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
