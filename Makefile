.PHONY: dev test lint gigsim eval

dev:
	uv run uvicorn apps.api.main:app --reload

test:
	uv run pytest

lint:
	uv run ruff check .

gigsim:
	uv run python -m gigsim_local

eval:
	uv run python -m evals.runners.run_demo_eval --output evals/results/synthetic-retrieval-dev.json --table-output evals/results/synthetic-retrieval-table.md
	uv run python -m evals.runners.run_simulator_risk_eval --output evals/results/synthetic-simulator-risk.json
	uv run python -m evals.runners.run_simulator_outcomes --output evals/results/synthetic-simulator-outcomes.json
	uv run python -m evals.runners.run_claim_verification_eval --output evals/results/synthetic-claim-verification.json
