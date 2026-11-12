from agent.nodes.claim_sanitizer import sanitize_proposal


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
            {"claim": "Verified project summary.", "status": "supported"},
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
