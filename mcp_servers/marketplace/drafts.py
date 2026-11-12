"""SQLite-backed local proposal drafts with idempotency, audit logging, and rate limiting."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposal_drafts (
    idempotency_key TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    cover_letter TEXT NOT NULL,
    price REAL NOT NULL,
    connects_cost INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    screening_answers TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    result TEXT NOT NULL,
    trace_id TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


class DraftRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    idempotency_key: str
    cover_letter: str
    price: float
    connects_cost: int
    screening_answers: list[str] = Field(default_factory=list)
    status: Literal["draft"] = "draft"
    created_at: datetime | None = None


class ProposalDraftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    outcome: Literal["preview", "created", "already_exists"]
    draft: DraftRecord
    connects_cost_if_submitted: int
    connects_spent: Literal[0] = 0
    external_action_taken: Literal[False] = False


class IdempotencyConflict(ValueError):
    """The idempotency key was already used for a different proposal payload."""


class RateLimitExceeded(RuntimeError):
    """The user exceeded the configured write rate."""


def payload_hash(
    job_id: str, cover_letter: str, price: float, screening_answers: list[str] | None = None
) -> str:
    canonical = json.dumps(
        [job_id, cover_letter, price, screening_answers or []], ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class MarketplaceStore:
    def __init__(self, path: Path | None = None, rate_limit_per_minute: int | None = None) -> None:
        self._path = path
        self._rate_limit = rate_limit_per_minute

    @property
    def path(self) -> Path:
        return self._path or Path(
            os.environ.get("GIGBID_MARKETPLACE_DB", "data/local/marketplace.sqlite3")
        )

    @property
    def rate_limit(self) -> int:
        if self._rate_limit is not None:
            return self._rate_limit
        return int(os.environ.get("GIGBID_MARKETPLACE_RATE_LIMIT", "20"))

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.executescript(_SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(proposal_drafts)")}
        if "screening_answers" not in columns:  # databases created before answers were stored
            connection.execute(
                "ALTER TABLE proposal_drafts ADD COLUMN screening_answers TEXT NOT NULL DEFAULT '[]'"
            )
        return connection

    def get_draft(self, idempotency_key: str) -> tuple[DraftRecord, str] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT job_id, idempotency_key, cover_letter, price, connects_cost, "
                "created_at, payload_hash, screening_answers FROM proposal_drafts "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            return None
        return DraftRecord(
            job_id=row[0],
            idempotency_key=row[1],
            cover_letter=row[2],
            price=row[3],
            connects_cost=row[4],
            created_at=datetime.fromisoformat(row[5]),
            screening_answers=json.loads(row[7]),
        ), row[6]

    def create_draft(self, record: DraftRecord, digest: str) -> tuple[DraftRecord, bool]:
        created_at = datetime.now(UTC)
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO proposal_drafts (idempotency_key, job_id, payload_hash, "
                "cover_letter, price, connects_cost, created_at, screening_answers) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(idempotency_key) DO NOTHING",
                (
                    record.idempotency_key,
                    record.job_id,
                    digest,
                    record.cover_letter,
                    record.price,
                    record.connects_cost,
                    created_at.isoformat(),
                    json.dumps(record.screening_answers),
                ),
            )
            created = cursor.rowcount == 1
        stored = self.get_draft(record.idempotency_key)
        if stored is None or stored[1] != digest:
            raise IdempotencyConflict("idempotency key was already used for a different proposal")
        return stored[0], created

    def enforce_rate_limit(self, user_id: str, tool: str) -> None:
        cutoff = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        with closing(self._connect()) as connection:
            (count,) = connection.execute(
                "SELECT COUNT(*) FROM audit_log WHERE user_id = ? AND tool = ? AND ts >= ?",
                (user_id, tool, cutoff),
            ).fetchone()
        if count >= self.rate_limit:
            raise RateLimitExceeded("rate limit exceeded; retry after one minute")

    def audit(
        self,
        user_id: str,
        tool: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        trace_id: str,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO audit_log (ts, user_id, tool, arguments, result, trace_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(),
                    user_id,
                    tool,
                    json.dumps(arguments, sort_keys=True),
                    json.dumps(result, sort_keys=True),
                    trace_id,
                ),
            )
