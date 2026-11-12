import math
from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

RetrieveFn = Callable[[str], list[dict[str, Any]]]
GradeFn = Callable[[str, list[dict[str, Any]]], dict[str, Any]]
RewriteFn = Callable[[str, list[dict[str, Any]], str], str]


class CorrectiveRAGState(TypedDict, total=False):
    query: str
    evidence: list[dict[str, Any]]
    relevance_scores: list[float]
    feedback: str
    attempts: int
    accepted: bool


def build_corrective_retrieval_graph(
    retrieve_fn: RetrieveFn,
    grade_fn: GradeFn,
    rewrite_fn: RewriteFn,
    max_attempts: int = 2,
    minimum_relevance: float = 0.6,
):
    """Build bounded retrieve/grade/rewrite V8; models are injected and evaluated separately."""
    if not 0 <= max_attempts <= 5:
        raise ValueError("max_attempts must be between 0 and 5")
    if not 0 <= minimum_relevance <= 1:
        raise ValueError("minimum_relevance must be between 0 and 1")

    def retrieve_node(state: CorrectiveRAGState) -> dict[str, Any]:
        query = state.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        evidence = retrieve_fn(query)
        if not isinstance(evidence, list):
            raise TypeError("retriever must return a list of evidence items")
        return {"evidence": evidence}

    def grade_node(state: CorrectiveRAGState) -> dict[str, Any]:
        query = state["query"]
        evidence = state.get("evidence", [])
        grade = grade_fn(query, evidence)
        if not isinstance(grade, dict):
            raise TypeError("grader must return an object")
        scores = grade.get("scores")
        feedback = grade.get("feedback", "")
        if not isinstance(scores, list):
            raise TypeError("grader scores must be a list")
        if not all(
            isinstance(score, (int, float))
            and math.isfinite(score)
            and 0 <= score <= 1
            for score in scores
        ):
            raise ValueError("grader scores must be finite values between 0 and 1")
        if len(scores) != len(evidence):
            raise ValueError("grader must return one relevance score per evidence item")
        if not isinstance(feedback, str):
            raise TypeError("grader feedback must be a string")
        average_score = sum(scores) / len(scores) if scores else 0
        return {
            "relevance_scores": scores,
            "feedback": feedback,
            "accepted": bool(evidence) and average_score >= minimum_relevance,
        }

    def rewrite_node(state: CorrectiveRAGState) -> dict[str, Any]:
        query = rewrite_fn(
            state["query"], state.get("evidence", []), state.get("feedback", "")
        )
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query rewriter must return a non-empty string")
        return {"query": query, "attempts": state.get("attempts", 0) + 1}

    def route_after_grade(state: CorrectiveRAGState) -> str:
        if state.get("accepted") or state.get("attempts", 0) >= max_attempts:
            return END
        return "rewrite"

    graph = StateGraph(CorrectiveRAGState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("grade", grade_node)
    graph.add_node("rewrite", rewrite_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges("grade", route_after_grade, {"rewrite": "rewrite", END: END})
    graph.add_edge("rewrite", "retrieve")
    return graph.compile()
