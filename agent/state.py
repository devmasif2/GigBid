from typing import Any, TypedDict


class GigBidState(TypedDict, total=False):
    job: dict[str, Any]
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    client_history: dict[str, Any]
    marketplace_policy: dict[str, Any]
    marketplace_policy_source: str
    fit_report: dict[str, Any]
    decision: str
    evidence: list[dict[str, Any]]
    price_quote: dict[str, Any]
    proposal_draft: dict[str, Any]
    claim_verification: list[dict[str, Any]]
    claim_verification_before_sanitization: list[dict[str, Any]]
    critique: dict[str, Any]
    compliance_verdict: dict[str, Any]
    approval_status: str
    approval_payload: dict[str, Any]
    decision_reason: str
    revision_count: int
    approval_error: str
    draft_publication: dict[str, Any]
    errors: list[str]
    execution_trace: list[dict[str, Any]]
    style_memory: list[dict[str, Any]]
    outcome_memory: list[dict[str, Any]]
    memory_events: list[dict[str, Any]]
    edit_count: int
    step_budget: int
    token_budget: int
    budget_status: str
    budget_steps_used: int
    budget_tokens_used: int


class ConversationState(TypedDict, total=False):
    conversation_id: str
    client_message: str
    available_slots: list[str]
    conversation_draft: dict[str, Any]
    approval_status: str
    approval_error: str
    execution_trace: list[dict[str, Any]]
    style_memory: list[dict[str, Any]]
    outcome_memory: list[dict[str, Any]]
    memory_events: list[dict[str, Any]]
