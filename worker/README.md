# Saved-search worker

The dependency-free worker provides the assignment's local scheduling and restart-safe
idempotency foundation. Searches and run claims are stored in SQLite. A duplicate worker cannot
claim the same `(search_id, scheduled_for)` occurrence twice, and failures are recorded
explicitly instead of being treated as successful runs.

The adapter callback is intentionally injected by the caller; the CLI's default callback only
demonstrates the scheduling contract and does not access a marketplace.

```python
from worker.scheduler import SavedSearch, SearchStore, run_due

store = SearchStore("data/local/worker.sqlite3")
store.save(SavedSearch("ml", "python machine learning", 900, time.time()))
run_due(store, marketplace_search_jobs)
```

This is a local worker primitive, not a distributed queue or production scheduler. Redis,
multi-user authentication, and live marketplace execution remain out of scope.
