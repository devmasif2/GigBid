from worker.scheduler import SavedSearch, SearchStore, run_due


def test_saved_search_runs_once_and_advances_schedule(tmp_path):
    store = SearchStore(tmp_path / "worker.sqlite3")
    store.save(SavedSearch("ml", "python", 60, 100))
    calls: list[str] = []

    assert run_due(store, lambda query: calls.append(query) or [{"job_id": "job-1"}], now=100) == 1
    assert calls == ["python"]
    assert run_due(store, lambda query: calls.append(query) or [], now=100) == 0
    assert store.due(159) == []
    assert store.due(160)[0].next_run_at == 160
    store.close()


def test_failed_run_is_recorded_and_schedule_is_not_repeated(tmp_path):
    store = SearchStore(tmp_path / "worker.sqlite3")
    store.save(SavedSearch("broken", "timeout", 30, 50))

    try:
        run_due(store, lambda _: (_ for _ in ()).throw(RuntimeError("marketplace unavailable")), now=50)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected search failure")

    assert run_due(store, lambda _: [], now=50) == 0
    status = store.connection.execute(
        "SELECT status, result_json FROM search_runs WHERE search_id='broken'"
    ).fetchone()
    assert status["status"] == "failed"
    assert "marketplace unavailable" in status["result_json"]
    store.close()
