from agent.budgets import check_budget


def test_step_budget_moves_thread_to_attention():
    result = check_budget({"step_budget": 1, "execution_trace": [{"node": "one"}]})

    assert result["budget_status"] == "needs_attention"
    assert result["approval_status"] == "needs_attention"


def test_token_budget_moves_thread_to_attention():
    result = check_budget({"token_budget": 1, "client_message": "too many tokens"})

    assert result["budget_status"] == "needs_attention"
    assert result["budget_tokens_used"] > 1


def test_budget_gate_accepts_normal_thread():
    result = check_budget({"step_budget": 2, "token_budget": 100, "client_message": "hello"})

    assert result["budget_status"] == "ok"
