import json
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from mcp_servers.portfolio.service import Portfolio

portfolio = Portfolio()
mcp = FastMCP("GigBid Portfolio")
READ_ONLY = ToolAnnotations(readOnlyHint=True)


@mcp.tool(annotations=READ_ONLY)
def search_evidence(
    requirement: str, k: int = 5, filters: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Find portfolio evidence relevant to a requirement; filters accept type, project, or skill."""
    return [
        item.model_dump(mode="json")
        for item in portfolio.search_evidence(requirement, k, filters)
    ]


@mcp.tool(annotations=READ_ONLY)
def get_case_study(case_id: str) -> dict[str, Any]:
    """Get a full case study by its evidence ID."""
    item = portfolio.get_case_study(case_id)
    if item is None:
        raise ValueError(f"case study not found: {case_id}")
    return item.model_dump(mode="json")


@mcp.tool(annotations=READ_ONLY)
def list_skills() -> list[str]:
    """List skills explicitly represented in the portfolio evidence."""
    return portfolio.list_skills()


@mcp.resource("portfolio://case/{case_id}")
def case_study_resource(case_id: str) -> str:
    """Read the full content of a case study."""
    item = portfolio.get_case_study(case_id)
    if item is None:
        raise ValueError(f"case study not found: {case_id}")
    return item.model_dump_json()


@mcp.resource("portfolio://proposal/{proposal_id}")
def proposal_resource(proposal_id: str) -> str:
    """Read a past proposal, including its recorded outcome."""
    item = portfolio.get_proposal(proposal_id)
    if item is None:
        raise ValueError(f"proposal not found: {proposal_id}")
    return item.model_dump_json()


@mcp.prompt()
def answer_screening_question(question: str) -> str:
    """Draft a screening answer using retrieved portfolio evidence, without adding unsupported claims."""
    evidence = portfolio.search_evidence(question, k=5)
    evidence_text = json.dumps(
        [item.model_dump(mode="json") for item in evidence], ensure_ascii=False
    )
    return (
        "Answer the screening question using only the supplied portfolio evidence. "
        "Do not invent experience; say when the evidence is insufficient.\n"
        f"Question: {question}\nEvidence: {evidence_text}"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
