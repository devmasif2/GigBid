import pytest

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


@pytest.mark.parametrize("line", [
    "My experience includes ten years in finance.",
    "I've delivered 50 dashboards.",
    "Our team has shipped hundreds of projects.",
    "Previously, I designed systems for banks.",
    "We specialize in data engineering.",
])
def test_common_uncited_experience_claims_are_flagged_even_with_valid_quote(line):
    evidence = [{"id": "case-1", "content": "Built a Python reporting workflow."}]
    result = verify_claims(f'{line}\n[case-1] "Built a Python reporting workflow."', evidence)
    assert [item["status"] for item in result] == ["unsupported", "supported"]


def test_empty_evidence_cannot_support_empty_quote():
    result = verify_claims('[case-1] ""', [{"id": "case-1", "content": ""}])
    assert result[0]["status"] == "unsupported"


@pytest.mark.parametrize("line", [
    '[case-1] "Verified project." plus 500 clients.',
    "[missing] invented experience",
    '[case-1] "Verified project.',
])
def test_malformed_citation_is_rejected_even_with_a_valid_quote(line):
    evidence = [{"id": "case-1", "content": "Verified project."}]
    result = verify_claims(f'{line}\n[case-1] "Verified project."', evidence)
    assert [item["status"] for item in result] == ["unsupported", "supported"]
