import pytest

from agent.nodes.claim_sanitizer import sanitize_proposal
from rag.verify import verify_claims


def test_sanitizer_removes_unsupported_lines_and_their_citations():
    state = {
        "proposal_draft": {
            "cover_letter": (
                "I would be glad to discuss this project.\n"
                '[case-1] "Verified project summary."\n'
                "I have ten years of experience."
            ),
            "evidence_ids": ["case-1", "invented"],
        },
        "claim_verification": [
            {"claim": "I have ten years of experience.", "status": "unsupported"},
            {"claim": "Verified project summary.", "status": "supported", "source_lines": [1]},
        ],
    }

    result = sanitize_proposal(state)

    assert result["proposal_draft"]["cover_letter"].splitlines() == [
        "I would be glad to discuss this project.",
        '[case-1] "Verified project summary."',
    ]
    assert result["proposal_draft"]["evidence_ids"] == ["case-1"]
    assert result["claim_verification_before_sanitization"] == state["claim_verification"]
    assert [claim["status"] for claim in result["claim_verification"]] == ["supported"]


def test_sanitizer_removes_bad_quote_without_removing_supported_citation():
    evidence = [{"id": "case-1", "content": "Built a Python reporting workflow."}]
    text = (
        '[case-1] "Built a Python reporting workflow."\n'
        '[case-1] "Built a Python reporting workflow for 100 clients."'
    )
    result = sanitize_proposal({
        "proposal_draft": {"cover_letter": text, "evidence_ids": ["case-1"]},
        "claim_verification": verify_claims(text, evidence),
    })
    assert result["proposal_draft"]["cover_letter"] == (
        '[case-1] "Built a Python reporting workflow."'
    )
    assert result["proposal_draft"]["evidence_ids"] == ["case-1"]


def test_sanitizer_does_not_leave_uncited_multiline_draft():
    text = "Hello there.\nI would enjoy discussing this project."
    result = sanitize_proposal({
        "proposal_draft": {"cover_letter": text, "evidence_ids": []},
        "claim_verification": verify_claims(text, []),
    })
    assert result["proposal_draft"]["cover_letter"] == ""


def test_source_lines_are_remapped_after_earlier_line_removal():
    text = 'I have ten years of experience.\n[case-1] "Verified project."'
    result = sanitize_proposal({
        "proposal_draft": {"cover_letter": text, "evidence_ids": ["case-1"]},
        "claim_verification": verify_claims(text, [{"id": "case-1", "content": "Verified project."}]),
    })
    assert result["claim_verification"][0]["source_lines"] == [0]


@pytest.mark.parametrize("positions", [None, "", 0, [True], [-1], [1]])
@pytest.mark.parametrize("status", ["supported", "unsupported"])
def test_sanitizer_rejects_invalid_source_lines(positions, status):
    with pytest.raises(ValueError, match="invalid claim source line"):
        sanitize_proposal({
            "proposal_draft": {"cover_letter": "A line.", "evidence_ids": []},
            "claim_verification": [{
                "claim": "A line.", "status": status, "source_lines": positions,
            }],
        })


def test_legacy_unsupported_claim_removes_all_duplicate_lines():
    result = sanitize_proposal({
        "proposal_draft": {"cover_letter": "Unverified.\nKeep.\nUnverified.", "evidence_ids": []},
        "claim_verification": [{"claim": "Unverified.", "status": "unsupported"}],
    })
    assert result["proposal_draft"]["cover_letter"] == "Keep."


def test_legacy_supported_check_is_not_retained_after_line_removal():
    result = sanitize_proposal({
        "proposal_draft": {"cover_letter": "Unverified.", "evidence_ids": []},
        "claim_verification": [
            {"claim": "Unverified.", "status": "unsupported"},
            {"claim": "Unverified.", "status": "supported"},
        ],
    })
    assert result["proposal_draft"]["cover_letter"] == ""
    assert result["claim_verification"] == []
