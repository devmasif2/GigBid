import asyncio
import hashlib
import math
import os
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from pydantic import ValidationError

from agent import marketplace_mcp_client
from agent.nodes.analyst import analyze_job
from agent.nodes.claim_sanitizer import sanitize_proposal
from agent.nodes.claim_verifier import verify_proposal
from agent.nodes.compliance import MISSING_ANSWERS_REASON, check_compliance
from agent.nodes.critic import critique_proposal
from agent.nodes.fit_matcher import match_fit_mcp
from agent.nodes.pricing import price_job
from agent.nodes.risk_assessor import assess_risk
from agent.nodes.writer import SCREENING_PLACEHOLDER, write_proposal
from agent.state import GigBidState
from mcp_servers.marketplace.drafts import ProposalDraftResult
from mcp_servers.marketplace.local_sample import SampleJob
from mcp_servers.portfolio.service import Portfolio
from rag.verify import verify_claims

Node = Callable[[GigBidState], dict[str, Any]]
DraftPublisher = Callable[..., Awaitable[ProposalDraftResult]]


async def _job_matches_marketplace(job: dict[str, Any]) -> bool:
    try:
        supplied = SampleJob.model_validate(job)
    except ValidationError as error:
        raise marketplace_mcp_client.MarketplaceMCPError("Invalid job for marketplace analysis") from error
    current = await marketplace_mcp_client.get_job(supplied.job_id)
    return current is not None and current == supplied


def _route_parallel(state: GigBidState) -> list[Send]:
    if "job" not in state:
        raise ValueError("bid graph input must contain a job")
    branch_input = {"job": state["job"]}
    return [
        Send("analyst", branch_input),
        Send("risk_assessor", branch_input),
        Send("fit_matcher", branch_input),
    ]


def _decision_node(state: GigBidState, minimum_fit_score: float, maximum_risk_score: float):
    fit_report = state.get("fit_report", {})
    risk_report = state.get("risk_report", {})
    evidence = state.get("evidence", [])
    fit_score = fit_report.get("score", 0.0)
    risk_score = risk_report.get("score", 1.0)

    if risk_score >= maximum_risk_score:
        decision = "skip"
        reason = "Risk score meets or exceeds the configured maximum."
    elif fit_score < minimum_fit_score or not evidence:
        decision = "skip"
        reason = "Insufficient retrieved portfolio evidence for the configured fit threshold."
    elif any(item.get("data_kind") != "real" for item in evidence):
        decision = "watch"
        reason = "Retrieved evidence is synthetic or unverified; it cannot support a real proposal."
    else:
        decision = "bid"
        reason = "Fit and risk thresholds passed with explicitly real portfolio evidence."
    return {"decision": decision, "decision_reason": reason, "revision_count": 0}


def _route_decision(state: GigBidState) -> str:
    return "price" if state.get("decision") == "bid" else END


def _route_critique(state: GigBidState) -> str:
    critique = state.get("critique", {})
    if critique.get("passed") is True:
        return "compliance"
    if state.get("revision_count", 0) < 2:
        return "revise"
    return "compliance"


def _revise(state: GigBidState) -> dict[str, int]:
    return {"revision_count": state.get("revision_count", 0) + 1}


def _approval_payload(state: GigBidState) -> dict[str, Any]:
    price_quote = state["price_quote"]
    payload = {
        "job": state["job"],
        "proposal_draft": state["proposal_draft"],
        "evidence": state.get("evidence", []),
        "risk_report": state["risk_report"],
        "price_quote": price_quote,
        "claim_verification": state.get("claim_verification", []),
        "marketplace_policy": state.get("marketplace_policy"),
        "marketplace_policy_source": state.get("marketplace_policy_source"),
        "dry_run": {
            "action": "create_proposal_draft",
            "connects_cost": price_quote.get("connects_cost"),
            "price": price_quote.get("recommended_price"),
            "external_action_taken": False,
        },
    }
    if state.get("compliance_verdict", {}).get("passed") is False:
        payload["edit_validation"] = state["compliance_verdict"]
    return payload


def _approval(state: GigBidState) -> dict[str, Any]:
    evidence = state.get("evidence", [])
    updated: dict[str, Any] = {}
    response = interrupt(_approval_payload(state))

    while isinstance(response, dict) and response.get("action") == "edit":
        cover_letter = response.get("cover_letter")
        if not isinstance(cover_letter, str) or not cover_letter.strip():
            raise ValueError("edited cover_letter must be a non-empty string")

        current_state = {**state, **updated}
        answers = response.get("screening_answers")
        if answers is None:
            answers = current_state["proposal_draft"].get("screening_answers", [])
        questions = current_state["job"].get("screening_questions", [])
        if (
            not isinstance(answers, list)
            or len(answers) != len(questions)
            or any(not isinstance(answer, str) or len(answer) > 5000 for answer in answers)
        ):
            raise ValueError("screening_answers must contain one string per question")
        draft = {
            **current_state["proposal_draft"],
            "cover_letter": cover_letter,
            "screening_answers": answers,
        }
        verification = verify_claims(cover_letter, evidence)
        sanitized = sanitize_proposal(
            {"proposal_draft": draft, "claim_verification": verification}
        )
        verification_before_sanitization = sanitized[
            "claim_verification_before_sanitization"
        ]
        draft = sanitized["proposal_draft"]
        verification = verify_claims(draft["cover_letter"], evidence)
        answer_checks = [
            {**check, "screening_question_index": index}
            for index, answer in enumerate(answers)
            if answer.strip() and answer.strip() != SCREENING_PLACEHOLDER
            for check in verify_claims(answer, evidence)
        ]
        revised_state = {
            **current_state,
            **sanitized,
            "proposal_draft": draft,
            "claim_verification": [*verification, *answer_checks],
        }
        critique = critique_proposal(revised_state)["critique"]
        revised_state["critique"] = critique
        verdict = check_compliance(revised_state)["compliance_verdict"]
        updated = {
            "proposal_draft": draft,
            "claim_verification": [*verification, *answer_checks],
            "claim_verification_before_sanitization": verification_before_sanitization,
            "critique": critique,
            "compliance_verdict": verdict,
        }
        response = interrupt(
            {
                **_approval_payload({**state, **updated}),
                "edit_validation": {
                    "passed": verdict["passed"],
                    "reasons": verdict["reasons"],
                },
            }
        )

    if not isinstance(response, dict) or response.get("action") not in {"approve", "reject"}:
        raise ValueError("approval response action must be 'approve', 'reject', or 'edit'")
    if response["action"] == "approve" and (
        updated.get("compliance_verdict", state.get("compliance_verdict", {})).get("passed")
        is False
    ):
        updated["approval_status"] = "needs_attention"
        updated["approval_error"] = (
            "The edited draft did not pass re-verification and compliance."
        )
    else:
        updated["approval_status"] = (
            "approved" if response["action"] == "approve" else "rejected"
        )
    return updated


def build_bid_graph(
    portfolio: Portfolio | None = None,
    minimum_fit_score: float = 0.6,
    maximum_risk_score: float = 0.7,
    checkpointer: Any | None = None,
    draft_publisher: DraftPublisher | None = None,
):
    if not 0 <= minimum_fit_score <= 1:
        raise ValueError("minimum_fit_score must be between 0 and 1")
    if not 0 <= maximum_risk_score <= 1:
        raise ValueError("maximum_risk_score must be between 0 and 1")

    workflow = StateGraph(GigBidState)
    workflow.add_node("analyst", analyze_job)
    async def risk_assessor_async(state: GigBidState) -> dict[str, Any]:
        if os.environ.get("GIGBID_MARKETPLACE_MODE", "sample") != "gigsim":
            return assess_risk(state)
        if not await _job_matches_marketplace(state["job"]):
            raise marketplace_mcp_client.MarketplaceMCPError(
                "Job details changed; start a new analysis"
            )
        client_id = state["job"].get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise marketplace_mcp_client.MarketplaceMCPError("Job has no client ID for risk assessment")
        history = await marketplace_mcp_client.get_client_history(client_id)
        data = history.model_dump(mode="json")
        return {**assess_risk({**state, "client_history": data}), "client_history": data}

    def risk_assessor_sync(state: GigBidState) -> dict[str, Any]:
        return asyncio.run(risk_assessor_async(state))

    workflow.add_node("risk_assessor", RunnableLambda(risk_assessor_sync, risk_assessor_async))
    async def fit_matcher_async(state: GigBidState) -> dict[str, Any]:
        return await match_fit_mcp(
            {"job_spec": analyze_job(state)["job_spec"]}, portfolio
        )

    def fit_matcher_sync(state: GigBidState) -> dict[str, Any]:
        return asyncio.run(fit_matcher_async(state))

    workflow.add_node("fit_matcher", RunnableLambda(fit_matcher_sync, fit_matcher_async))
    workflow.add_node(
        "decide",
        lambda state: _decision_node(state, minimum_fit_score, maximum_risk_score),
    )
    workflow.add_node("price", price_job)
    workflow.add_node("writer", write_proposal)
    workflow.add_node("verify_claims", verify_proposal)
    workflow.add_node("sanitize_claims", sanitize_proposal)
    workflow.add_node("critic", critique_proposal)
    workflow.add_node("revise", _revise)
    async def compliance_async(state: GigBidState) -> dict[str, Any]:
        if os.environ.get("GIGBID_MARKETPLACE_MODE", "sample") != "gigsim":
            return {
                **check_compliance(state),
                "marketplace_policy_source": "unavailable: local sample only",
            }
        policy = await marketplace_mcp_client.get_marketplace_policy()
        job = await marketplace_mcp_client.get_job(state["job"]["job_id"])
        if job is None:
            raise marketplace_mcp_client.MarketplaceMCPError("Job no longer exists")
        current_job = job.model_dump(mode="json")
        try:
            supplied = SampleJob.model_validate(state["job"])
        except ValidationError as error:
            raise marketplace_mcp_client.MarketplaceMCPError("Invalid job for marketplace analysis") from error
        if supplied != job:
            raise marketplace_mcp_client.MarketplaceMCPError(
                "Job details changed; start a new analysis"
            )
        cost = current_job["connects_cost"]
        if cost is None:
            raise marketplace_mcp_client.MarketplaceMCPError("Job Connects cost is unavailable")
        policy_data = policy.model_dump(mode="json")
        quote = {
            **state["price_quote"],
            "connects_cost": math.ceil(cost * policy.connects_multiplier),
        }
        return {
            **check_compliance({**state, "marketplace_policy": policy_data}),
            "marketplace_policy": policy_data,
            "marketplace_policy_source": "local GigSim stand-in",
            "price_quote": quote,
        }

    def compliance_sync(state: GigBidState) -> dict[str, Any]:
        return asyncio.run(compliance_async(state))

    workflow.add_node("compliance", RunnableLambda(compliance_sync, compliance_async))
    workflow.add_node("approval", _approval)

    publish = draft_publisher or marketplace_mcp_client.create_proposal_draft

    async def publish_draft_async(state: GigBidState) -> dict[str, Any]:
        mode = os.environ.get("GIGBID_MARKETPLACE_MODE", "sample")
        expected_mode = (
            "gigsim" if state.get("marketplace_policy_source") == "local GigSim stand-in"
            else "sample"
        )
        if mode != expected_mode:
            return {
                "approval_status": "needs_attention",
                "approval_error": "Marketplace mode changed; start a new analysis.",
                "draft_publication": {"outcome": "not_created", "reason": "Marketplace mode changed."},
            }
        if state.get("marketplace_policy_source") == "local GigSim stand-in":
            policy = await marketplace_mcp_client.get_marketplace_policy()
            if (
                policy.model_dump(mode="json") != state.get("marketplace_policy")
                or not await _job_matches_marketplace(state["job"])
            ):
                return {
                    "approval_status": "needs_attention",
                    "approval_error": "Marketplace policy or job details changed; start a new analysis.",
                    "draft_publication": {
                        "outcome": "not_created",
                        "reason": "Marketplace policy or job details changed after review.",
                    },
                }
        price = state["price_quote"].get("recommended_price")
        if price is None:
            return {
                "draft_publication": {
                    "outcome": "not_created",
                    "reason": "No recommended price; set one before creating a draft.",
                }
            }
        job_id = state["job"]["job_id"]
        cover_letter = state["proposal_draft"]["cover_letter"]
        answers = state["proposal_draft"].get("screening_answers") or []
        digest = hashlib.sha256(
            f"{job_id}\n{price}\n{cover_letter}\n{answers}".encode()
        ).hexdigest()
        result = await publish(
            job_id=job_id,
            cover_letter=cover_letter,
            price=price,
            screening_answers=answers,
            idempotency_key=f"bid-{digest[:32]}",
            dry_run=False,
        )
        return {"draft_publication": result.model_dump(mode="json")}

    def publish_draft_sync(state: GigBidState) -> dict[str, Any]:
        return asyncio.run(publish_draft_async(state))

    workflow.add_node("publish_draft", RunnableLambda(publish_draft_sync, publish_draft_async))
    workflow.add_conditional_edges(START, _route_parallel, ["analyst", "risk_assessor", "fit_matcher"])
    workflow.add_edge(["analyst", "risk_assessor", "fit_matcher"], "decide")
    workflow.add_conditional_edges(
        "decide", _route_decision, {"price": "price", END: END}
    )
    workflow.add_edge("price", "writer")
    workflow.add_edge("writer", "verify_claims")
    workflow.add_edge("verify_claims", "sanitize_claims")
    workflow.add_edge("sanitize_claims", "critic")
    workflow.add_conditional_edges(
        "critic",
        _route_critique,
        {"compliance": "compliance", "revise": "revise"},
    )
    workflow.add_edge("revise", "writer")
    workflow.add_conditional_edges(
        "compliance",
        lambda state: "approval"
        if (
            state.get("compliance_verdict", {}).get("passed") is True
            or state.get("compliance_verdict", {}).get("reasons") == [MISSING_ANSWERS_REASON]
        )
        else END,
        {"approval": "approval", END: END},
    )
    workflow.add_conditional_edges(
        "approval",
        lambda state: "publish_draft" if state.get("approval_status") == "approved" else END,
        {"publish_draft": "publish_draft", END: END},
    )
    workflow.add_edge("publish_draft", END)
    return workflow.compile(checkpointer=checkpointer or InMemorySaver())
