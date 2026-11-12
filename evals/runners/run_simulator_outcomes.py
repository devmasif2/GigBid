"""Evaluate synthetic proposal components on an isolated local simulator, never a live marketplace."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx

from agent.nodes.analyst import analyze_job
from agent.nodes.pricing import price_job
from agent.nodes.risk_assessor import assess_risk
from agent.nodes.writer import write_proposal
from evals.runners.run_demo_eval import DEFAULT_DATASET, Dataset, LexicalIndex
from gigsim_local.app import create_app
from gigsim_local.engine import SimConfig
from rag.variants.v0_naive import retrieve
from rag.variants.v1_decomposition import retrieve_by_requirements
from rag.verify import verify_claims

PERSONAS = {"ai_ml": "ml", "web": "web", "data": "data"}
STRATEGIES = ("v0", "v1")
USER_HEADERS = {"Authorization": "Bearer eval-user"}
ADMIN_HEADERS = {"Authorization": "Bearer eval-admin"}


def build_candidate(job: dict[str, Any], index: LexicalIndex, strategy: str) -> dict[str, Any]:
    """Use only the public job and fictional portfolio, not simulator hidden preferences."""
    spec = analyze_job({"job": job})["job_spec"]
    risk = assess_risk({"job": job})["risk_report"]
    quote = price_job({"job": job, "decision": "bid"})["price_quote"]
    skills = {skill.casefold() for item in index.items for skill in item["skills"]}
    required = spec["required_skills"]
    matched = [skill for skill in required if skill.casefold() in skills]
    if risk["score"] >= 0.7:
        return {"decision": "skip", "reason": "risk", "risk_score": risk["score"]}
    if not required or not matched or len(matched) / len(required) < 0.4:
        return {"decision": "skip", "reason": "insufficient synthetic skill coverage", "risk_score": risk["score"]}
    if quote["recommended_price"] is None or quote["recommended_price"] <= 0:
        return {"decision": "skip", "reason": "no positive price", "risk_score": risk["score"]}
    if strategy == "v0":
        results = retrieve(" ".join([job["title"], *required]), index, k=3)
    elif strategy == "v1":
        results = retrieve_by_requirements(required, index, k_per_requirement=3, k=3)
    else:
        raise ValueError(f"unknown strategy: {strategy}")
    if not results:
        return {"decision": "skip", "reason": "no synthetic evidence", "risk_score": risk["score"]}
    draft = write_proposal({"job_spec": spec, "evidence": results})["proposal_draft"]
    draft["screening_answers"] = [
        "I would discuss the scope and validation approach before starting."
        for _ in spec["screening_questions"]
    ]
    checks = verify_claims(draft["cover_letter"], results)
    return {
        "decision": "submit_simulated",
        "risk_score": risk["score"],
        "matched_skills": matched,
        "evidence_ids": draft["evidence_ids"],
        "cover_letter": draft["cover_letter"],
        "screening_answers": draft["screening_answers"],
        "price": quote["recommended_price"],
        "detected_unsupported_cover_claims": sum(
            check["status"] == "unsupported" for check in checks
        ),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    submitted = [row for row in rows if row["decision"] == "submit_simulated"]
    replies = sum(row["replied"] for row in submitted)
    hires = sum(row["hired"] for row in submitted)
    return {
        "jobs_considered": len(rows),
        "jobs_skipped": len(rows) - len(submitted),
        "simulated_proposals_submitted": len(submitted),
        "simulated_replies": replies,
        "simulated_hires": hires,
        "reply_rate_per_submitted": replies / len(submitted) if submitted else None,
        "hire_rate_per_submitted": hires / len(submitted) if submitted else None,
        "simulated_connects_spent": sum(row["connects_spent"] for row in submitted),
        "price_within_synthetic_fair_band_rate": (
            sum(row["price_in_fair_band"] for row in submitted) / len(submitted)
            if submitted else None
        ),
        "detected_unsupported_cover_claims_per_proposal": (
            sum(row["detected_unsupported_cover_claims"] for row in submitted) / len(submitted)
            if submitted else None
        ),
    }


async def evaluate(
    seed: int, jobs: int, clients: int, selected: int, dataset_path: Path = DEFAULT_DATASET
) -> dict[str, Any]:
    if jobs < 1 or clients < 1 or selected < 1:
        raise ValueError("jobs, clients and selected must be positive")
    raw = dataset_path.read_bytes()
    dataset = Dataset.model_validate_json(raw)
    indexes = {
        name: LexicalIndex([item for item in dataset.evidence if item.persona == name])
        for name in PERSONAS.values()
    }
    if any(not index.items for index in indexes.values()):
        raise ValueError("dataset must have synthetic evidence for ml, web and data personas")

    scenarios: dict[str, Any] = {}
    reference_ids: list[str] | None = None
    for strategy in STRATEGIES:
        # A fresh in-process app is the only destination: synthetic confirmation cannot reach a
        # configured external simulator or any real account.
        app = create_app(SimConfig(
            seed=seed, job_count=jobs, client_count=clients,
            user_tokens={"eval-user": "evaluation-only"}, admin_token="eval-admin",
            rate_limit_per_minute=max(1000, jobs * 5), initial_connects=jobs * 16,
        ))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://isolated-eval"
        ) as http:
            listings: list[dict[str, Any]] = []
            offset = 0
            while len(listings) < selected:
                response = await http.get(
                    "/jobs", headers=USER_HEADERS, params={"limit": 100, "offset": offset}
                )
                response.raise_for_status()
                page = response.json()
                if not page:
                    break
                listings.extend(page)
                offset += len(page)
            listings = listings[:selected]
            ids = [job["job_id"] for job in listings]
            if reference_ids is None:
                reference_ids = ids
            elif ids != reference_ids:
                raise RuntimeError("simulator scenarios did not use the same job set")
            rows = []
            for job in listings:
                persona = PERSONAS[job["category"]]
                candidate = build_candidate(job, indexes[persona], strategy)
                row = {"job_id": job["job_id"], "category": job["category"], "persona": persona, **candidate}
                if candidate["decision"] == "submit_simulated":
                    response = await http.post(
                        "/proposals", headers={**USER_HEADERS, "Idempotency-Key": f"create-{job['job_id']}"},
                        json={key: candidate[key] for key in ("cover_letter", "screening_answers", "price")}
                        | {"job_id": job["job_id"]},
                    )
                    response.raise_for_status()
                    proposal_id = response.json()["proposal_id"]
                    confirmation = await http.post(
                        f"/proposals/{proposal_id}/confirm",
                        headers={**USER_HEADERS, "Idempotency-Key": f"confirm-{job['job_id']}"},
                    )
                    confirmation.raise_for_status()
                    row["proposal_id"] = proposal_id
                    row["connects_spent"] = confirmation.json()["connects_spent"]
                rows.append(row)
            tick = await http.post("/sim/tick", headers=ADMIN_HEADERS, json={"hours": 120})
            tick.raise_for_status()
            events_response = await http.get("/events", headers=USER_HEADERS)
            events_response.raise_for_status()
            truth_response = await http.get("/sim/ground-truth", headers=ADMIN_HEADERS)
            truth_response.raise_for_status()
            truth = truth_response.json()["jobs"]
            statuses: dict[str, set[str]] = {}
            for event in events_response.json():
                if event["type"] == "proposal_status":
                    statuses.setdefault(event["proposal_id"], set()).add(event["status"])
            for row in rows:
                if row["decision"] == "submit_simulated":
                    observed = statuses.get(row["proposal_id"], set())
                    row["replied"] = "replied" in observed
                    row["hired"] = "hired" in observed
                    row["observed_statuses"] = sorted(observed)
                    band = truth[row["job_id"]]
                    row["price_in_fair_band"] = (
                        band["fair_price_min"] <= row["price"] <= band["fair_price_max"]
                    )
            balance_response = await http.get("/account/connects", headers=USER_HEADERS)
            balance_response.raise_for_status()
            overall = summarize(rows)
            if jobs * 16 - balance_response.json()["balance"] != overall["simulated_connects_spent"]:
                raise RuntimeError("simulator Connects accounting did not reconcile")
            scenarios[strategy] = {
                "overall": overall,
                "by_persona": {
                    persona: summarize([row for row in rows if row["persona"] == persona])
                    for persona in sorted({row["persona"] for row in rows})
                },
                "by_category": {
                    category: summarize([row for row in rows if row["category"] == category])
                    for category in sorted({row["category"] for row in rows})
                },
                "jobs": rows,
            }
    return {
        "scope": "isolated local GigSim stand-in and fictional portfolio; not the production bid graph",
        "seed": seed,
        "generated_jobs": jobs,
        "generated_clients": clients,
        "requested_visible_jobs": selected,
        "actual_visible_jobs": len(reference_ids or []),
        "job_ids": reference_ids,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "runtime": {"python": sys.version.split()[0]},
        "methods": {
            "selection": "first visible jobs in simulator API order; same set for each strategy",
            "decision": "risk score below 0.7, at least 40% of listed skills in fictional persona, positive price",
            "proposal": "deterministic writer quotes fictional evidence; scripted generic screening answers",
            "confirmation": "automatic synthetic-only confirmation in an isolated in-process simulator",
            "outcomes": "events observed after 120 simulated hours; rates use submitted proposals as denominator",
            "retrieval": "v0 bag-of-words cosine versus v1 per-requirement merge, up to 3 evidence items",
            "price": "posted budget midpoint compared with simulator hidden fair band after decisions",
            "claims": "existing limited verifier on generated cover letters only; no human or model judge",
        },
        "not_measured": [
            "human approval", "production graph decisions", "real user experience", "live submissions",
            "judge score", "tokens", "USD cost", "instructor hidden test",
        ],
        "scenarios": scenarios,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--jobs", type=int, default=150)
    parser.add_argument("--clients", type=int, default=40)
    parser.add_argument("--selected", type=int, default=100)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(
        asyncio.run(evaluate(args.seed, args.jobs, args.clients, args.selected, args.dataset)),
        indent=2, allow_nan=False,
    ) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        print(f"Wrote isolated synthetic simulator outcomes to {args.output}")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
