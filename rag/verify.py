import re
from typing import Any

from agent.handoffs import ClaimCheck

_CITATION = re.compile(r'^\[(?P<id>[^\]]+)\]\s+"(?P<claim>.*)"$')
_FIRST_PERSON_FACT = re.compile(
    r"\b(?:(?:I|we)(?:\s+|['’](?:ve|m|re)\s+)"
    r"(?:am|are|was|were|have|had|built|created|developed|led|worked|"
    r"delivered|achieved|managed|implemented|designed|shipped|completed|"
    r"helped|served|speciali[sz]e|experience|expertise|years)\b"
    r"|(?:my|our)\s+(?:experience|expertise|background|portfolio|clients|projects)\b"
    r"|(?:my|our)\s+team\s+(?:has|have|had|built|created|developed|delivered|shipped))",
    re.IGNORECASE,
)


def verify_claims(
    draft: str, evidence: list[dict[str, Any]], *, require_citation: bool = True
) -> list[dict[str, Any]]:
    """Verify cited evidence quotes exactly; flag unsupported first-person experience claims."""
    if not isinstance(draft, str):
        raise TypeError("draft must be a string")
    if not isinstance(evidence, list):
        raise TypeError("evidence must be a list")

    evidence_by_id = {
        item["id"]: " ".join(item["content"].split())
        for item in evidence
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("content"), str)
    }
    results: list[ClaimCheck] = []

    lines = draft.splitlines()
    for line_number, line in enumerate(lines):
        citation = _CITATION.fullmatch(line.strip())
        if citation is not None:
            evidence_id = citation.group("id")
            claim = " ".join(citation.group("claim").split())
            expected = evidence_by_id.get(evidence_id)
            if expected is None:
                status = "unsupported"
                explanation = "Citation does not refer to retrieved evidence."
            elif expected and claim == expected:
                status = "supported"
                explanation = "Quoted text exactly matches retrieved evidence."
            else:
                status = "unsupported"
                explanation = "Quoted text differs from the retrieved evidence."
            results.append(
                ClaimCheck(
                    claim=claim,
                    evidence_ids=[evidence_id],
                    status=status,
                    explanation=explanation,
                    source_lines=[line_number],
                )
            )
        elif line.lstrip().startswith("[") or _FIRST_PERSON_FACT.search(line):
            results.append(
                ClaimCheck(
                    claim=line.strip(),
                    status="unsupported",
                    explanation=(
                        "Citation must be an exact evidence quote on its own line."
                        if line.lstrip().startswith("[")
                        else "First-person experience claim has no evidence citation."
                    ),
                    source_lines=[line_number],
                )
            )

    if not results and draft.strip() and require_citation:
        results.append(
            ClaimCheck(
                claim=draft.strip(),
                status="unsupported",
                explanation="Draft contains no verifiable evidence citation.",
                source_lines=list(range(len(lines))),
            )
        )
    return [result.model_dump(mode="json") for result in results]
