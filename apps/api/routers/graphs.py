import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.marketplace_mcp_client import MarketplaceMCPError
from agent.mcp_client import PortfolioMCPError
from agent.observability import Trace, new_trace_id

_MCP_ERRORS = (PortfolioMCPError, MarketplaceMCPError)

router = APIRouter(prefix="/graphs", tags=["graphs"])
bid_graph = build_bid_graph()
conversation_graph = build_conversation_graph()


def configure_checkpointer(checkpointer: Any | None) -> None:
    global bid_graph, conversation_graph
    active_checkpointer = checkpointer or InMemorySaver()
    bid_graph = build_bid_graph(checkpointer=active_checkpointer)
    conversation_graph = build_conversation_graph(checkpointer=active_checkpointer)


class GraphStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(min_length=1, max_length=200)
    input: dict[str, Any]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "reject", "edit"]
    cover_letter: str | None = Field(default=None, max_length=20_000)
    message: str | None = Field(default=None, max_length=5000)
    screening_answers: list[Annotated[str, Field(max_length=5000)]] | None = Field(
        default=None, max_length=10
    )

    @model_validator(mode="after")
    def validate_edit(self) -> "ApprovalRequest":
        if self.action == "edit" and not (
            (self.cover_letter is not None and self.cover_letter.strip())
            or (self.message is not None and self.message.strip())
        ):
            raise ValueError("cover_letter or message is required when action is edit")
        if self.action != "edit" and (self.cover_letter is not None or self.message is not None):
            raise ValueError("edit text is only accepted when editing")
        if self.action != "edit" and self.screening_answers is not None:
            raise ValueError("screening_answers are only accepted when editing")
        return self


def _config(graph_name: str, thread_id: str, trace_id: str) -> dict[str, dict[str, str]]:
    return {
        "configurable": {"thread_id": f"{graph_name}:{thread_id}"},
        "metadata": {"trace_id": trace_id, "graph": graph_name},
    }


def _valid_trace_id(value: str | None) -> str:
    if value is None:
        return new_trace_id()
    try:
        return UUID(value).hex
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Trace-Id must be a UUID") from None


def _serialize_result(result: dict[str, Any]) -> dict[str, Any]:
    state = {key: value for key, value in result.items() if key != "__interrupt__"}
    interrupts = [
        item.value for item in result.get("__interrupt__", []) if hasattr(item, "value")
    ]
    return {
        "status": "interrupted" if interrupts else "completed",
        "state": state,
        "interrupts": interrupts,
    }


@router.get("/{graph_name}/{thread_id}")
async def get_graph_state(
    graph_name: Literal["bid", "conversation"], thread_id: str,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    graph = bid_graph if graph_name == "bid" else conversation_graph
    trace_id = _valid_trace_id(x_trace_id)
    snapshot = await graph.aget_state(_config(graph_name, thread_id, trace_id))
    if snapshot.created_at is None:
        raise HTTPException(status_code=404, detail="graph thread not found")
    interrupts = [item.value for item in snapshot.interrupts]
    return {
        "status": "interrupted" if interrupts else "running" if snapshot.next else "completed",
        "state": snapshot.values,
        "interrupts": interrupts,
        "observability": {"trace_id": trace_id},
    }


@router.post("/{graph_name}/start")
async def start_graph(
    graph_name: Literal["bid", "conversation"], request: GraphStartRequest,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    graph = bid_graph if graph_name == "bid" else conversation_graph
    trace_id = _valid_trace_id(x_trace_id)
    trace = Trace(trace_id)
    span = trace.span("graph.start")
    try:
        result = await graph.ainvoke(
            request.input, config=_config(graph_name, request.thread_id, trace_id)
        )
    except _MCP_ERRORS as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    span.finish(result)
    response = _serialize_result(result)
    response["observability"] = trace.finish(response["state"])
    return response


def _serialize_update(update: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in update.items():
        if key == "__interrupt__":
            serialized[key] = [
                item.value for item in value if hasattr(item, "value")
            ]
        else:
            serialized[key] = value
    return serialized


@router.post("/{graph_name}/stream")
async def stream_graph(
    graph_name: Literal["bid", "conversation"], request: GraphStartRequest,
    x_trace_id: str | None = Header(default=None),
) -> StreamingResponse:
    graph = bid_graph if graph_name == "bid" else conversation_graph
    trace_id = _valid_trace_id(x_trace_id)
    trace = Trace(trace_id)

    async def updates():
        interrupted = False
        try:
            async for update in graph.astream(
                request.input,
                config=_config(graph_name, request.thread_id, trace_id),
                stream_mode="updates",
            ):
                span = trace.span("graph.update")
                payload = _serialize_update(update)
                span.finish(payload)
                interrupted = interrupted or "__interrupt__" in payload
                yield f"event: update\ndata: {json.dumps(payload)}\n\n"
        except _MCP_ERRORS as error:
            yield f"event: error\ndata: {json.dumps({'detail': str(error)})}\n\n"
            return
        status = "interrupted" if interrupted else "completed"
        observability = trace.finish()
        yield f"event: complete\ndata: {json.dumps({'status': status})}\n\n"
        yield f"event: trace\ndata: {json.dumps(observability)}\n\n"

    return StreamingResponse(
        updates(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{graph_name}/{thread_id}/approval")
async def resume_graph(
    graph_name: Literal["bid", "conversation"],
    thread_id: str,
    request: ApprovalRequest,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    if graph_name == "conversation" and (
        request.cover_letter is not None or request.screening_answers is not None
        or (request.action == "edit" and request.message is None)
    ):
        raise HTTPException(status_code=422, detail="Provide message for conversation edits")
    if graph_name == "bid" and (
        request.message is not None
        or (request.action == "edit" and request.cover_letter is None)
    ):
        raise HTTPException(status_code=422, detail="Provide cover_letter for bid edits")
    graph = bid_graph if graph_name == "bid" else conversation_graph
    trace_id = _valid_trace_id(x_trace_id)
    trace = Trace(trace_id)
    snapshot = await graph.aget_state(_config(graph_name, thread_id, trace_id))
    if snapshot.created_at is None:
        raise HTTPException(status_code=404, detail="graph thread not found")
    if not snapshot.interrupts:
        raise HTTPException(status_code=409, detail="graph thread is not awaiting approval")
    if graph_name == "bid" and request.screening_answers is not None:
        questions = snapshot.values.get("job", {}).get("screening_questions", [])
        if len(request.screening_answers) != len(questions):
            raise HTTPException(status_code=422, detail="Provide one screening answer per question")
    try:
        result = await graph.ainvoke(
            Command(
                resume={
                    "action": request.action,
                    **(
                        {"cover_letter": request.cover_letter}
                        if request.cover_letter is not None
                        else {}
                    ),
                    **({"message": request.message} if request.message is not None else {}),
                    **(
                        {"screening_answers": request.screening_answers}
                        if request.screening_answers is not None
                        else {}
                    ),
                }
            ),
            config=_config(graph_name, thread_id, trace_id),
        )
    except _MCP_ERRORS as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    response = _serialize_result(result)
    response["observability"] = trace.finish(response["state"])
    return response


@router.post("/{graph_name}/{thread_id}/continue")
async def continue_graph(
    graph_name: Literal["bid", "conversation"], thread_id: str,
    x_trace_id: str | None = Header(default=None),
) -> dict[str, Any]:
    """Resume a run that stopped after an error; completed work is not repeated."""
    graph = bid_graph if graph_name == "bid" else conversation_graph
    trace_id = _valid_trace_id(x_trace_id)
    trace = Trace(trace_id)
    config = _config(graph_name, thread_id, trace_id)
    snapshot = await graph.aget_state(config)
    if snapshot.created_at is None:
        raise HTTPException(status_code=404, detail="graph thread not found")
    if snapshot.interrupts or not snapshot.next:
        raise HTTPException(status_code=409, detail="graph thread has nothing to continue")
    try:
        result = await graph.ainvoke(None, config=config)
    except _MCP_ERRORS as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    response = _serialize_result(result)
    response["observability"] = trace.finish(response["state"])
    return response
