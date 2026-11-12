from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.memory.store import trace_event
from agent.nodes.client_liaison import draft_client_response
from agent.nodes.compliance import prohibited_text_reasons
from agent.state import ConversationState
from rag.verify import verify_claims


def _approval(state: ConversationState) -> dict[str, Any]:
    draft = state["conversation_draft"]
    verdict: dict[str, Any] | None = None

    def payload() -> dict[str, Any]:
        result = {
            "conversation_id": state["conversation_id"],
            "draft": draft,
            "external_action_taken": False,
        }
        if verdict is not None:
            result["edit_validation"] = verdict
        return result

    response = interrupt(payload())
    while isinstance(response, dict) and response.get("action") == "edit":
        message = response.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 5000:
            raise ValueError("edited message must contain 1 to 5000 characters")
        reasons = prohibited_text_reasons(message)
        checks = verify_claims(message, [], require_citation=False)
        if any(check["status"] == "unsupported" for check in checks):
            reasons.append("Reply contains an unsupported portfolio claim.")
        verdict = {"passed": not reasons, "reasons": reasons}
        draft = {**draft, "message": message, "interview_slots": []}
        response = interrupt(payload())
    if not isinstance(response, dict) or response.get("action") not in {"approve", "reject"}:
        raise ValueError("approval response action must be 'approve', 'reject', or 'edit'")
    if response["action"] == "approve" and verdict is not None and not verdict["passed"]:
        return {
            "conversation_draft": draft,
            "approval_status": "needs_attention",
            "approval_error": "The edited reply did not pass safety checks.",
        }
    return {
        "conversation_draft": draft,
        "approval_status": "approved" if response["action"] == "approve" else "rejected",
    }


def _validate_input(state: ConversationState) -> dict[str, Any]:
    if not state.get("conversation_id") or not state.get("client_message"):
        raise ValueError("conversation graph requires conversation_id and client_message")
    return {
        "execution_trace": trace_event(
            state.get("execution_trace"),
            node="validate",
            status="completed",
            observation="conversation input validated",
        )
    }


def build_conversation_graph(checkpointer: Any | None = None):
    workflow = StateGraph(ConversationState)
    workflow.add_node("budget_gate", check_budget)
    workflow.add_node("validate", _validate_input)
    workflow.add_node("client_liaison", draft_client_response)
    workflow.add_node("approval", _approval)
    workflow.add_edge(START, "budget_gate")
    workflow.add_conditional_edges(
        "budget_gate",
        budget_route,
        {"continue": "validate", "attention": END},
    )
    workflow.add_edge("validate", "client_liaison")
    workflow.add_edge("client_liaison", "approval")
    workflow.add_edge("approval", END)
    return workflow.compile(checkpointer=checkpointer or InMemorySaver())
from agent.budgets import budget_route, check_budget
