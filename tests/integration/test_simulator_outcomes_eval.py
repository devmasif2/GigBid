import json
import subprocess
import sys

import pytest

from evals.runners.run_simulator_outcomes import evaluate, summarize


@pytest.mark.anyio
async def test_fixed_simulator_evaluation_is_reproducible_and_balanced():
    first = await evaluate(seed=2026, jobs=50, clients=10, selected=25)
    assert first == await evaluate(seed=2026, jobs=50, clients=10, selected=25)
    assert first["actual_visible_jobs"] == 25
    for data in first["scenarios"].values():
        rows = data["jobs"]
        assert [row["job_id"] for row in rows] == first["job_ids"]
        submitted = [row for row in rows if row["decision"] == "submit_simulated"]
        summary = data["overall"]
        assert summary["simulated_proposals_submitted"] == len(submitted)
        assert summary["simulated_replies"] == sum(row["replied"] for row in submitted)
        assert summary["simulated_hires"] == sum(row["hired"] for row in submitted)
        assert summary["simulated_connects_spent"] == sum(row["connects_spent"] for row in submitted)
        assert sum(part["jobs_considered"] for part in data["by_persona"].values()) == 25
        assert all(not row["hired"] or row["replied"] for row in submitted)
        assert all("submitted" in row["observed_statuses"] for row in submitted)
    assert first["scenarios"]["v0"]["overall"]["simulated_proposals_submitted"] > 0


@pytest.mark.anyio
async def test_zero_visible_jobs_are_reported_without_division_by_zero():
    result = await evaluate(seed=1, jobs=1, clients=1, selected=100)
    for scenario in result["scenarios"].values():
        if scenario["overall"]["simulated_proposals_submitted"] == 0:
            assert scenario["overall"]["reply_rate_per_submitted"] is None


def test_summarize_empty_and_reject_invalid_configuration():
    assert summarize([])["hire_rate_per_submitted"] is None
    assert summarize([])["price_within_synthetic_fair_band_rate"] is None


@pytest.mark.anyio
async def test_invalid_configuration_rejected():
    with pytest.raises(ValueError, match="positive"):
        await evaluate(seed=1, jobs=0, clients=1, selected=1)


def test_cli_creates_isolated_report(tmp_path):
    output = tmp_path / "outcomes.json"
    subprocess.run(
        [sys.executable, "-m", "evals.runners.run_simulator_outcomes",
         "--jobs", "20", "--clients", "5", "--selected", "10", "--output", str(output)],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(output.read_text())
    assert "not the production bid graph" in result["scope"]
    assert "human approval" in result["not_measured"]
    assert result["actual_visible_jobs"] == 10
