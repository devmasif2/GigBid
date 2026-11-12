"""Transparent baseline price recommendation from the posted budget."""

from typing import Any

from agent.handoffs import PriceQuote


def price_job(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    job = state.get("job")
    if job is None:
        raise ValueError("state must contain a job object")
    if not isinstance(job, dict):
        raise TypeError("job must be an object")
    budget = job.get("budget") or {}
    if not isinstance(budget, dict):
        raise TypeError("job.budget must be an object")

    minimum = budget.get("min")
    maximum = budget.get("max")
    currency = budget.get("currency")
    connects_cost = job.get("connects_cost")
    if minimum is not None and not isinstance(minimum, (int, float)):
        raise TypeError("job.budget.min must be numeric")
    if maximum is not None and not isinstance(maximum, (int, float)):
        raise TypeError("job.budget.max must be numeric")
    if connects_cost is not None and not isinstance(connects_cost, int):
        raise TypeError("job.connects_cost must be an integer")

    if minimum is not None and maximum is not None and maximum >= minimum:
        recommended_price = round((minimum + maximum) / 2, 2)
        rationale = (
            f"Midpoint of the posted {currency or 'unspecified-currency'} budget "
            f"range ({minimum:g}–{maximum:g})."
        )
    else:
        recommended_price = None
        rationale = "No valid posted budget range; a price recommendation needs human input."

    decision = state.get("decision", "watch")
    report = PriceQuote(
        recommended_price=recommended_price,
        currency=currency,
        rationale=rationale,
        connects_cost=connects_cost,
        action=decision,
    )
    return {"price_quote": report.model_dump(mode="json")}
