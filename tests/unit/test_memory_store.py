from agent.memory.store import promote_outcome_memory, promote_style_memory, trace_event


def test_trace_event_excludes_raw_payloads():
    trace = trace_event(None, node="writer", status="completed", observation="draft created")

    assert trace == [{
        "node": "writer",
        "status": "completed",
        "observation": "draft created",
    }]


def test_style_memory_requires_three_distinct_edits():
    memory, event = promote_style_memory(
        [], edited_text="Please remove the opening sentence.", prior_text="I am passionate.", edit_count=2
    )
    assert memory == [] and event is None

    memory, event = promote_style_memory(
        [], edited_text="Please remove the opening sentence.", prior_text="I am passionate.", edit_count=3
    )
    assert event and memory[0]["source"] == "repeated_user_edit"
    assert "passionate" not in memory[0]["rule"]


def test_outcome_memory_rejects_unrecognized_outcomes():
    memory, event = promote_outcome_memory([], job_category="data", outcome="client_text")
    assert memory == [] and event is None

    memory, event = promote_outcome_memory([], job_category="data", outcome="hired")
    assert event == {"kind": "outcome", "job_category": "data", "outcome": "hired"}
    assert memory == [event]
