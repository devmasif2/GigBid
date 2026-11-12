from rag.verify import verify_claims


def test_claim_verifier_accepts_exact_evidence_quote():
    evidence = [{"id": "case-1", "content": "Built a Python reporting workflow."}]

    result = verify_claims(
        'I would be glad to discuss this project.\n[case-1] "Built a Python reporting workflow."',
        evidence,
    )

    assert len(result) == 1
    assert result[0]["status"] == "supported"
    assert result[0]["evidence_ids"] == ["case-1"]


def test_claim_verifier_flags_changed_or_unknown_citations():
    evidence = [{"id": "case-1", "content": "Built a Python reporting workflow."}]

    result = verify_claims(
        '[case-1] "Built a Python reporting workflow for 100 clients."\n'
        '[missing] "Won every project."',
        evidence,
    )

    assert [claim["status"] for claim in result] == ["unsupported", "unsupported"]


def test_claim_verifier_flags_uncited_first_person_experience():
    result = verify_claims("I have ten years of experience.", [])

    assert result[0]["status"] == "unsupported"
    assert "no evidence citation" in result[0]["explanation"]
