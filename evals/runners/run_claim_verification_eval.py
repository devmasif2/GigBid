"""Measure heuristic claim verification before and after proposal sanitization."""

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.nodes.claim_sanitizer import sanitize_proposal
from rag.verify import verify_claims

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data/claim_verification_dev.json"


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    content: str = Field(min_length=1)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    evidence: list[Evidence]
    draft: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "Case":
        if len({item.id for item in self.evidence}) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")
        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    data_kind: str
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_values(self) -> "Dataset":
        if self.data_kind != "synthetic":
            raise ValueError("claim evaluation data must be synthetic")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        return self


def _metrics(checks: list[dict[str, Any]]) -> dict[str, Any]:
    unsupported = sum(check.get("status") == "unsupported" for check in checks)
    return {
        "claims": len(checks),
        "unsupported_claims": unsupported,
        "unsupported_claim_rate": unsupported / len(checks) if checks else 0.0,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "proposals": len(rows),
        "unsupported_claims_per_proposal": statistics.mean(
            row["after"]["unsupported_claims"] for row in rows
        ),
        "unsupported_claim_rate": (
            sum(row["after"]["unsupported_claims"] for row in rows)
            / sum(row["after"]["claims"] for row in rows)
            if sum(row["after"]["claims"] for row in rows)
            else 0.0
        ),
        "removed_lines_per_proposal": statistics.mean(row["removed_lines"] for row in rows),
    }


def evaluate(dataset: Dataset, dataset_sha256: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for case in dataset.cases:
        evidence = [item.model_dump() for item in case.evidence]
        before_checks = verify_claims(case.draft, evidence, require_citation=False)
        sanitized = sanitize_proposal({
            "proposal_draft": {"cover_letter": case.draft, "evidence_ids": [item["id"] for item in evidence]},
            "claim_verification": before_checks,
        })
        after_draft = sanitized["proposal_draft"]["cover_letter"]
        after_checks = verify_claims(after_draft, evidence, require_citation=False)
        rows.append({
            "case_id": case.id,
            "persona": case.persona,
            "before": _metrics(before_checks),
            "after": _metrics(after_checks),
            "removed_lines": len(case.draft.splitlines()) - len(after_draft.splitlines()),
            "draft_after": after_draft,
        })

    return {
        "dataset": {
            "name": dataset.name,
            "version": dataset.version,
            "data_kind": dataset.data_kind,
            "sha256": dataset_sha256,
            "case_count": len(dataset.cases),
        },
        "runtime": {"python": sys.version.split()[0]},
        "scope": (
            "synthetic heuristic claim-verification component evaluation; "
            "the checker supplies the labels and this is not semantic truth verification"
        ),
        "methods": {
            "before": "verify_claims on the original proposal with require_citation=False",
            "sanitization": "remove unsupported source lines before critique",
            "after": "re-run verify_claims on the sanitized proposal with require_citation=False",
        },
        "overall": {
            "before": _summarize([
                {**row, "after": row["before"]} for row in rows
            ]),
            "after": _summarize(rows),
        },
        "by_persona": {
            persona: {
                "before": _summarize([
                    {**row, "after": row["before"]} for row in rows if row["persona"] == persona
                ]),
                "after": _summarize([row for row in rows if row["persona"] == persona]),
            }
            for persona in sorted({row["persona"] for row in rows})
        },
        "cases": rows,
        "not_measured": [
            "semantic entailment", "claim splitting", "LLM judge scores",
            "human ratings", "real portfolio accuracy",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    result = evaluate(dataset, hashlib.sha256(raw).hexdigest())
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote claim verification evaluation to {args.output}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
