"""A small SQLite-backed saved-search worker.

The worker is intentionally dependency-free: it provides durable scheduling and idempotent
claims while the API/Marketplace adapter remains responsible for job retrieval.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SavedSearch:
    search_id: str
    query: str
    interval_seconds: int
    next_run_at: float


class SearchStore:
    def __init__(self, path: str | Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (
                search_id TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0),
                next_run_at REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS search_runs (
                search_id TEXT NOT NULL,
                scheduled_for REAL NOT NULL,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (search_id, scheduled_for),
                FOREIGN KEY (search_id) REFERENCES saved_searches(search_id)
            );
            """
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def save(self, search: SavedSearch) -> None:
        self.connection.execute(
            """
            INSERT INTO saved_searches(search_id, query, interval_seconds, next_run_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(search_id) DO UPDATE SET query=excluded.query,
              interval_seconds=excluded.interval_seconds, next_run_at=excluded.next_run_at,
              active=1
            """,
            (search.search_id, search.query, search.interval_seconds, search.next_run_at),
        )
        self.connection.commit()

    def due(self, now: float) -> list[SavedSearch]:
        rows = self.connection.execute(
            """
            SELECT search_id, query, interval_seconds, next_run_at
            FROM saved_searches WHERE active=1 AND next_run_at <= ? ORDER BY next_run_at
            """,
            (now,),
        ).fetchall()
        return [SavedSearch(row["search_id"], row["query"], row["interval_seconds"], row["next_run_at"]) for row in rows]

    def claim(self, search: SavedSearch) -> bool:
        """Claim one scheduled occurrence; duplicate workers safely get False."""
        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO search_runs(search_id, scheduled_for, status)
            VALUES (?, ?, 'running')
            """,
            (search.search_id, search.next_run_at),
        )
        if cursor.rowcount != 1:
            return False
        self.connection.execute(
            "UPDATE saved_searches SET next_run_at=? WHERE search_id=?",
            (search.next_run_at + search.interval_seconds, search.search_id),
        )
        self.connection.commit()
        return True

    def finish(self, search: SavedSearch, results: Iterable[dict[str, object]]) -> None:
        self.connection.execute(
            """
            UPDATE search_runs SET status='completed', result_json=?
            WHERE search_id=? AND scheduled_for=? AND status='running'
            """,
            (json.dumps(list(results), sort_keys=True), search.search_id, search.next_run_at),
        )
        self.connection.commit()

    def fail(self, search: SavedSearch, error: str) -> None:
        self.connection.execute(
            """
            UPDATE search_runs SET status='failed', result_json=?
            WHERE search_id=? AND scheduled_for=? AND status='running'
            """,
            (json.dumps({"error": error}), search.search_id, search.next_run_at),
        )
        self.connection.commit()


def run_due(
    store: SearchStore,
    search: Callable[[str], Iterable[dict[str, object]]],
    *,
    now: float | None = None,
) -> int:
    """Run each due search once and return the number of completed runs."""
    completed = 0
    for saved in store.due(time.time() if now is None else now):
        if not store.claim(saved):
            continue
        try:
            store.finish(saved, search(saved.query))
        except Exception as error:
            store.fail(saved, str(error))
            raise
        completed += 1
    return completed
