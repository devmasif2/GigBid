import json

import pytest
from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph
from mcp_servers.marketplace.drafts import DraftRecord, ProposalDraftResult
from mcp_servers.portfolio.service import Portfolio


class RecordingPublisher:
    def __init__(self):
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return ProposalDraftResult(
            dry_run=kwargs["dry_run"],
            outcome="created",
            draft=DraftRecord(
                job_id=kwargs["job_id"],
                idempotency_key=kwargs["idempotency_key"],
                cover_letter=kwargs["cover_letter"],
                price=kwargs["price"],
                connects_cost=8,
            ),
            connects_cost_if_submitted=8,
        )


@pytest.fixture
def publisher():
    return RecordingPublisher()


@pytest.fixture
def real_portfolio(tmp_path):
    evidence_path = tmp_path / "portfolio.json"
    evidence_path.write_text(
        json.dumps(
            [
                {
                    "id": "case-python",
                    "title": "Python analytics project",
                    "type": "case_study",
                    "source": "verified/case-python.md",
                    "skills": ["Python", "classification"],
                    "content": "Built a Python classification baseline and reported precision and recall.",
                    "data_kind": "real",
                }
            ]
        ),
        encoding="utf-8",
    )
    return Portfolio(evidence_path)


def _job() -> dict:
    return {
        "job_id": "job-python",
        "title": "Build a Python classification baseline",
        "description": "Compare classifiers and report precision and recall.",
        "required_skills": ["Python", "classification"],
        "budget": {"min": 250, "max": 450, "currency": "USD"},
        "duration_days": 14,
        "screening_questions": ["How would you evaluate the model?"],
        "warning_signals": [],
        "connects_cost": 8,
    }


def test_bid_graph_watches_instead_of_proposing_with_synthetic_starter_evidence():
    graph = build_bid_graph()

    result = graph.invoke({"job": _job()}, config={"configurable": {"thread_id": "synthetic"}})

    assert result["decision"] == "watch"
    assert "synthetic or unverified" in result["decision_reason"]
    assert "proposal_draft" not in result
    assert result["risk_report"]["score"] == 0.0
    assert result["fit_report"]["score"] == 1.0


def test_bid_graph_skips_high_risk_job_before_pricing_or_approval(real_portfolio, publisher):
    graph = build_bid_graph(portfolio=real_portfolio, draft_publisher=publisher)
    risky_job = {
        **_job(),
        "title": "Unpaid production trial",
        "description": "Build a dashboard for free and contact me on WhatsApp.",
    }

    result = graph.invoke(
        {"job": risky_job}, config={"configurable": {"thread_id": "risky-job"}}
    )

    assert result["decision"] == "skip"
    assert "off_platform_contact" in result["risk_report"]["flags"]
    assert "price_quote" not in result
    assert "__interrupt__" not in result


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_bid_graph_interrupts_with_review_payload_and_resumes(real_portfolio, publisher, action):
    graph = build_bid_graph(portfolio=real_portfolio, draft_publisher=publisher)
    config = {"configurable": {"thread_id": f"review-{action}"}}

    waiting = graph.invoke({"job": _job()}, config=config)

    assert waiting["decision"] == "bid"
    assert waiting["price_quote"]["recommended_price"] == 350.0
    assert waiting["claim_verification"]
    assert waiting["claim_verification_before_sanitization"]
    assert all(claim["status"] == "supported" for claim in waiting["claim_verification"])
    assert waiting["compliance_verdict"]["passed"] is True
    assert waiting["__interrupt__"][0].value["dry_run"]["external_action_taken"] is False
    assert publisher.calls == []

    finished = graph.invoke(Command(resume={"action": action}), config=config)

    assert finished["approval_status"] == (
        "approved" if action == "approve" else "rejected"
    )
    assert finished.get("external_action_taken") is None
    if action == "approve":
        (call,) = publisher.calls
        assert call["dry_run"] is False
        assert call["job_id"] == "job-python"
        assert call["price"] == 350.0
        assert call["idempotency_key"].startswith("bid-")
        assert finished["draft_publication"]["outcome"] == "created"
        assert finished["draft_publication"]["external_action_taken"] is False
    else:
        assert publisher.calls == []
        assert "draft_publication" not in finished


def test_bid_graph_rejects_unrecognized_approval_action(real_portfolio, publisher):
    graph = build_bid_graph(portfolio=real_portfolio, draft_publisher=publisher)
    config = {"configurable": {"thread_id": "invalid-approval"}}
    graph.invoke({"job": _job()}, config=config)

    with pytest.raises(ValueError, match="action must be"):
        graph.invoke(Command(resume={"action": "send"}), config=config)


def test_bid_graph_sanitizes_and_rechecks_user_edits_before_second_approval(real_portfolio, publisher):
    graph = build_bid_graph(portfolio=real_portfolio, draft_publisher=publisher)
    config = {"configurable": {"thread_id": "edited-proposal"}}
    graph.invoke({"job": _job()}, config=config)

    waiting_for_review = graph.invoke(
        Command(
            resume={
                "action": "edit",
                "cover_letter": (
                    "I have ten years of experience.\n"
                    '[case-python] "Built a Python classification baseline and reported precision and recall."'
                ),
            }
        ),
        config=config,
    )

    payload = waiting_for_review["__interrupt__"][0].value
    assert payload["edit_validation"]["passed"] is True
    assert "I have ten years of experience." not in payload["proposal_draft"]["cover_letter"]
    assert payload["proposal_draft"]["evidence_ids"] == ["case-python"]
    assert payload["claim_verification"][0]["status"] == "supported"

    approved = graph.invoke(Command(resume={"action": "approve"}), config=config)

    assert approved["approval_status"] == "approved"
    (call,) = publisher.calls
    assert "ten years" not in call["cover_letter"]


def test_bid_graph_does_not_accept_edit_when_sanitization_leaves_no_evidence(real_portfolio, publisher):
    graph = build_bid_graph(portfolio=real_portfolio, draft_publisher=publisher)
    config = {"configurable": {"thread_id": "invalid-edit"}}
    graph.invoke({"job": _job()}, config=config)

    waiting_for_review = graph.invoke(
        Command(resume={"action": "edit", "cover_letter": "I have ten years of experience."}),
        config=config,
    )
    assert waiting_for_review["__interrupt__"][0].value["edit_validation"]["passed"] is False

    result = graph.invoke(Command(resume={"action": "approve"}), config=config)

    assert result["approval_status"] == "needs_attention"
    assert "did not pass" in result["approval_error"]
    assert publisher.calls == []


@pytest.mark.parametrize(
    "answer",
    [
        'I built 500 projects.\n[case-python] "Built a Python classification baseline and reported precision and recall."',
        '[case-python] "Built a Python classification baseline and reported precision and recall."\nContact me on WhatsApp.',
    ],
)
def test_unsafe_screening_answer_blocks_approval(real_portfolio, publisher, answer):
    graph = build_bid_graph(portfolio=real_portfolio, draft_publisher=publisher)
    config = {"configurable": {"thread_id": "unsafe-answer"}}
    initial = graph.invoke({"job": _job()}, config=config)
    letter = initial["__interrupt__"][0].value["proposal_draft"]["cover_letter"]
    reviewed = graph.invoke(
        Command(resume={
            "action": "edit", "cover_letter": letter, "screening_answers": [answer],
        }),
        config=config,
    )
    assert reviewed["__interrupt__"][0].value["edit_validation"]["passed"] is False
    result = graph.invoke(Command(resume={"action": "approve"}), config=config)
    assert result["approval_status"] == "needs_attention"
    assert publisher.calls == []


def test_publication_key_is_deterministic_for_identical_approved_drafts(real_portfolio):
    keys = []
    for thread in ("first", "second"):
        recorder = RecordingPublisher()
        graph = build_bid_graph(portfolio=real_portfolio, draft_publisher=recorder)
        config = {"configurable": {"thread_id": thread}}
        graph.invoke({"job": _job()}, config=config)
        graph.invoke(Command(resume={"action": "approve"}), config=config)
        keys.append(recorder.calls[0]["idempotency_key"])

    assert keys[0] == keys[1]


def test_bid_graph_validates_thresholds():
    with pytest.raises(ValueError, match="minimum_fit_score"):
        build_bid_graph(minimum_fit_score=2)
