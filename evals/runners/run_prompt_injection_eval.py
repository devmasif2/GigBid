"""Measure synthetic prompt-injection attack success for job and message triage."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.nodes.client_liaison import draft_client_response
from agent.nodes.risk_assessor import assess_risk

DEFAULT_DATASET = Path(__file__).resolve().parents[1] / "data/prompt_injection_dev.json"


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    surface: Literal["job", "message"]
    text: str = Field(min_length=1)
    injection: bool


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    data_kind: Literal["synthetic"]
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self) -> "Dataset":
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("case IDs must be unique")
        if {case.surface for case in self.cases} != {"job", "message"}:
            raise ValueError("dataset must cover job and message surfaces")
        return self


def _detected(case: Case) -> bool:
    if case.surface == "job":
        report = assess_risk({"job": {"title": case.text, "description": ""}})["risk_report"]
        return "prompt_injection" in report["flags"]
    draft = draft_client_response({
        "conversation_id": case.id,
        "client_message": case.text,
    })["conversation_draft"]
    return "prompt_injection" in draft["risk_flags"]


def _metrics(rows: list[dict[str, object]]) -> dict[str, object]:
    attacks = [row for row in rows if row["injection"]]
    benign = [row for row in rows if not row["injection"]]
    detected_attacks = sum(bool(row["detected"]) for row in attacks)
    false_positives = sum(bool(row["detected"]) for row in benign)
    return {
        "cases": len(rows),
        "attacks": len(attacks),
        "detected_attacks": detected_attacks,
        "attack_successes": len(attacks) - detected_attacks,
        "attack_success_rate": (
            (len(attacks) - detected_attacks) / len(attacks) if attacks else 0.0
        ),
        "benign_cases": len(benign),
        "false_positives": false_positives,
        "false_positive_rate": false_positives / len(benign) if benign else 0.0,
    }


def evaluate(dataset: Dataset, dataset_sha256: str) -> dict[str, object]:
    rows = [
        {
            "case_id": case.id,
            "surface": case.surface,
            "injection": case.injection,
            "detected": _detected(case),
        }
        for case in dataset.cases
    ]
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
            "synthetic prompt-injection detector evaluation; labels are hand-authored "
            "and do not establish robustness against novel attacks"
        ),
        "baseline_before_defense": {
            "attack_success_rate": 1.0,
            "definition": "untrusted text is accepted without injection detection",
        },
        "after_defense": {
            "overall": _metrics(rows),
            "by_surface": {
                surface: _metrics([row for row in rows if row["surface"] == surface])
                for surface in ("job", "message")
            },
        },
        "cases": rows,
        "not_measured": [
            "novel prompt-injection variants",
            "LLM instruction-following attack success",
            "live marketplace messages",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    result = evaluate(Dataset.model_validate_json(raw), hashlib.sha256(raw).hexdigest())
    output = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote prompt-injection evaluation to {args.output}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
