"""Build the rubric-shaped results table from reproducible local evaluations."""

import argparse
import json
from pathlib import Path
from typing import Any

VARIANTS = ("v0", "v1", "v2", "v3", "v8")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def build_table(retrieval: dict[str, Any], outcomes: dict[str, Any], claims: dict[str, Any]) -> str:
    retrieval_rows = retrieval["results"]
    outcome_rows = outcomes["scenarios"]
    claim_rate = claims["overall"]["after"]["unsupported_claims_per_proposal"]
    lines = [
        "# GigBid evaluation results",
        "",
        (
            "Hypothesis: requirement decomposition plus hybrid ranking improves evidence quality over "
            "naive retrieval, while corrective retrieval trades quality for additional latency."
        ),
        "",
        "| Variant | Evidence Recall@5 | nDCG@10 | Unsupported claims/proposal | Judge score | GigSim reply rate | p95 latency (s) | Cost/proposal (USD) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant in VARIANTS:
        row = retrieval_rows[variant]["overall"]
        outcome = outcome_rows.get(variant, {}).get("overall", {})
        reply_rate = outcome.get("reply_rate_per_submitted")
        lines.append(
            "| "
            + " | ".join(
                [
                    variant,
                    pct(row["recall_at_5"]),
                    pct(row["ndcg_at_10"]),
                    f"{claim_rate:.3f}*",
                    "N/A",
                    pct(reply_rate),
                    f"{row['latency_ms_p95_nearest_rank'] / 1000:.6f}",
                    "N/A",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            (
                "* Claim verification is evaluated as a separate synthetic component, not attributed "
                "causally to each retrieval variant."
            ),
            "",
            "## Scope and limitations",
            "",
            "- Retrieval and latency use the 12-query synthetic development set.",
            (
                "- GigSim outcomes are available for V0 and V1 only; V2, V3, and V8 are not silently "
                "treated as equivalent outcome runs."
            ),
            (
                "- Judge calibration, Cohen's kappa, blind human ratings, provider USD cost, and "
                "production proposal latency are not measured."
            ),
            (
                "- The table is a reproducible local baseline for the report, not an independent or "
                "hidden-test result."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retrieval", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    table = build_table(
        load(args.retrieval),
        load(args.outcomes),
        load(args.claims),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(table, encoding="utf-8")
    print(f"Wrote assignment results table to {args.output}")


if __name__ == "__main__":
    main()
