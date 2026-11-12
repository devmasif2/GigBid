"""Single-user local portfolio source store with transactional reindexing."""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import TypeAdapter

from mcp_servers.portfolio.service import EvidenceItem
from rag.ingest.portfolio import (
    MAX_FILE_BYTES,
    SourceDocument,
    evidence_from_text,
    extract_pdf_text,
)


class SourceConflict(ValueError):
    """The source was modified since the caller last read it."""


class SourceNotFound(ValueError):
    """The requested source does not exist."""


class PortfolioStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS portfolio_sources (
                    freelancer_id TEXT NOT NULL, source_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, metadata TEXT NOT NULL, evidence TEXT NOT NULL,
                    PRIMARY KEY (freelancer_id, source_id)
                )"""
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS portfolio_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT)"
            )

    def list_sources(self) -> list[dict]:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            rows = connection.execute(
                "SELECT metadata, revision FROM portfolio_sources ORDER BY freelancer_id, source_id"
            ).fetchall()
        return [{**json.loads(metadata), "revision": revision} for metadata, revision in rows]

    def put(self, document: SourceDocument, raw: bytes, expected_revision: int | None) -> int:
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError("source exceeds size limit")
        suffix = Path(document.path).suffix.lower()
        if suffix not in {".md", ".txt", ".pdf"}:
            raise ValueError("only .md, .txt and .pdf files are supported")
        text = extract_pdf_text(raw, document.source_id) if suffix == ".pdf" else raw.decode("utf-8")
        evidence = evidence_from_text(document, text, f"local-upload:{document.source_id}")
        payload = TypeAdapter(list[EvidenceItem]).dump_json(evidence).decode()
        metadata = document.model_dump_json()
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM portfolio_sources WHERE freelancer_id=? AND source_id=?",
                (document.freelancer_id, document.source_id),
            ).fetchone()
            if current is None:
                if expected_revision is not None:
                    raise SourceNotFound("source does not exist")
                revision = connection.execute(
                    "INSERT INTO portfolio_revisions DEFAULT VALUES RETURNING id"
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO portfolio_sources VALUES (?, ?, ?, ?, ?)",
                    (document.freelancer_id, document.source_id, revision, metadata, payload),
                )
            else:
                if expected_revision != current[0]:
                    raise SourceConflict("source already exists or was modified; refresh first")
                revision = connection.execute(
                    "INSERT INTO portfolio_revisions DEFAULT VALUES RETURNING id"
                ).fetchone()[0]
                connection.execute(
                    "UPDATE portfolio_sources SET revision=?, metadata=?, evidence=? "
                    "WHERE freelancer_id=? AND source_id=?",
                    (revision, metadata, payload, document.freelancer_id, document.source_id),
                )
        return revision

    def delete(self, freelancer_id: str, source_id: str, expected_revision: int) -> None:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision FROM portfolio_sources WHERE freelancer_id=? AND source_id=?",
                (freelancer_id, source_id),
            ).fetchone()
            if current is None:
                raise SourceNotFound("source does not exist")
            if expected_revision != current[0]:
                raise SourceConflict("source was modified; refresh first")
            connection.execute(
                "DELETE FROM portfolio_sources WHERE freelancer_id=? AND source_id=?",
                (freelancer_id, source_id),
            )


def read_store_items(path: Path) -> list[EvidenceItem]:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)) as connection:
        rows = connection.execute(
            "SELECT evidence FROM portfolio_sources ORDER BY freelancer_id, source_id"
        ).fetchall()
    adapter = TypeAdapter(list[EvidenceItem])
    return [item for (payload,) in rows for item in adapter.validate_json(payload)]
