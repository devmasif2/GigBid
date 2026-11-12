import asyncio
import os

import pytest
from langgraph.types import Command

from agent.graphs.conversation_graph import build_conversation_graph


def _run_recovery(database_url: str) -> None:
    async def scenario() -> None:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        thread = {"configurable": {"thread_id": "postgres-recovery-test"}}
        async with AsyncPostgresSaver.from_conn_string(database_url) as first_saver:
            await first_saver.setup()
            first_graph = build_conversation_graph(checkpointer=first_saver)
            waiting = await first_graph.ainvoke(
                {
                    "conversation_id": "conversation-1",
                    "client_message": "Could you share your availability for an interview?",
                    "available_slots": ["Monday 10:00 UTC"],
                },
                config=thread,
            )
            assert waiting["__interrupt__"]

        async with AsyncPostgresSaver.from_conn_string(database_url) as second_saver:
            second_graph = build_conversation_graph(checkpointer=second_saver)
            completed = await second_graph.ainvoke(
                Command(resume={"action": "approve"}),
                config=thread,
            )
            assert completed["approval_status"] == "approved"
            assert completed["conversation_draft"]["message"]

    asyncio.run(scenario())


def test_postgres_checkpoint_survives_checkpointer_restart():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is not configured")
    try:
        _run_recovery(database_url)
    except (OSError, RuntimeError) as error:
        pytest.skip(f"PostgreSQL is unavailable: {error}")
