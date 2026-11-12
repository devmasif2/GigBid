"""Small deterministic graph budget gates."""

from typing import Any

from agent.observability import estimate_tokens

DEFAULT_STEP_BUDGET = 40
DEFAULT_TOKEN_BUDGET = 12_000


def check_budget(state: dict[str, Any]) -> dict[str, Any]:
    step_budget = state.get("step_budget", DEFAULT_STEP_BUDGET)
    token_budget = state.get("token_budget", DEFAULT_TOKEN_BUDGET)
    steps_used = len(state.get("execution_trace", []))
    tokens_used = estimate_tokens(state)
    if steps_used >= step_budget:
        return {
            "approval_status": "needs_attention",
            "approval_error": f"Step budget exceeded ({step_budget}).",
            "budget_status": "needs_attention",
            "budget_steps_used": steps_used,
            "budget_tokens_used": tokens_used,
        }
    if tokens_used > token_budget:
        return {
            "approval_status": "needs_attention",
            "approval_error": f"Token budget exceeded ({token_budget}).",
            "budget_status": "needs_attention",
            "budget_steps_used": steps_used,
            "budget_tokens_used": tokens_used,
        }
    return {
        "budget_status": "ok",
        "budget_steps_used": steps_used,
        "budget_tokens_used": tokens_used,
    }


def budget_route(state: dict[str, Any]) -> str:
    return "attention" if state.get("budget_status") == "needs_attention" else "continue"
