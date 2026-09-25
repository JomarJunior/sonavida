"""The persona's memory: one SQLite file, append-only, with full-text recall (R-2).

`data-model.md` is the source of truth for the schema. Nothing here ever deletes a
row (FR-026); the only update is erasure (`memory/erasure.py`, R-8), which clears two
columns and rewrites tokens in already-stored text.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

KINDS = frozenset(
    {
        "seed",
        "self-aware",
        "presence",
        "time-away",
        "intention",
        "attempt",
        "attempt-seen",
        "finished",
        "abandoned",
        "kept",
        "submitted",
        "verdict",
        "experience",
        "studio-not-ready",
        "interrupted",
        "attempt-failed",
        "lost-thread",
        "thinking-of-leaving",
        "departed",
        "chose-nothing",
    }
)

PIECE_STATES = frozenset(
    {
        "in-progress",
        "finished",
        "abandoned",
        "kept",
        "submitted",
        "accepted",
        "rejected",
        "exhibited",
        "declined",
        "taken-down",
    }
)

ATTEMPT_OUTCOMES = frozenset(
    {"kept-as-final", "discarded", "reworked", "did-not-come-out", "interrupted"}
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS self (
    persona_id TEXT PRIMARY KEY,
    public_name TEXT NOT NULL,
    self_knowledge TEXT NOT NULL,
    born_at TEXT NOT NULL,
    departed_at TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    reason TEXT,
    importance INTEGER NOT NULL,
    piece_id TEXT,
    visitor_pseudonym TEXT,
    visitor_name TEXT,
    source_sequence INTEGER
);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    text, reason, content='entries', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, text, reason)
        VALUES (new.id, new.text, coalesce(new.reason, ''));
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, text, reason)
        VALUES('delete', old.id, old.text, coalesce(old.reason, ''));
    INSERT INTO entries_fts(rowid, text, reason)
        VALUES (new.id, new.text, coalesce(new.reason, ''));
END;

CREATE TABLE IF NOT EXISTS pieces (
    id TEXT PRIMARY KEY,
    intention_entry INTEGER NOT NULL,
    state TEXT NOT NULL,
    title TEXT,
    statement TEXT,
    suggested_labels TEXT NOT NULL DEFAULT '[]',
    labels TEXT,
    image_path TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    piece_id TEXT NOT NULL,
    asked TEXT NOT NULL,
    image_path TEXT,
    seen TEXT,
    outcome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS inbox (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    experiences_acknowledged_through INTEGER NOT NULL DEFAULT 0,
    erasures_acknowledged_through INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class SelfRecord:
    persona_id: str
    public_name: str
    self_knowledge: dict[str, Any]
    born_at: datetime
    departed_at: datetime | None


@dataclass(frozen=True)
class Entry:
    id: int
    at: datetime
    kind: str
    text: str
    reason: str | None
    importance: int
    piece_id: str | None
    visitor_pseudonym: str | None
    visitor_name: str | None
    source_sequence: int | None


@dataclass(frozen=True)
class PieceRecord:
    id: str
    intention_entry: int
    state: str
    title: str | None
    statement: str | None
    suggested_labels: frozenset[str]
    labels: frozenset[str] | None
    image_path: str | None


@dataclass(frozen=True)
class Attempt:
    id: int
    piece_id: str
    asked: str
    image_path: str | None
    seen: str | None
    outcome: str


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _entry_from_row(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        at=_parse(row["at"]),
        kind=row["kind"],
        text=row["text"],
        reason=row["reason"],
        importance=row["importance"],
        piece_id=row["piece_id"],
        visitor_pseudonym=row["visitor_pseudonym"],
        visitor_name=row["visitor_name"],
        source_sequence=row["source_sequence"],
    )


def _piece_from_row(row: sqlite3.Row) -> PieceRecord:
    labels = json.loads(row["labels"]) if row["labels"] is not None else None
    return PieceRecord(
        id=row["id"],
        intention_entry=row["intention_entry"],
        state=row["state"],
        title=row["title"],
        statement=row["statement"],
        suggested_labels=frozenset(json.loads(row["suggested_labels"])),
        labels=frozenset(labels) if labels is not None else None,
        image_path=row["image_path"],
    )


def _attempt_from_row(row: sqlite3.Row) -> Attempt:
    return Attempt(
        id=row["id"],
        piece_id=row["piece_id"],
        asked=row["asked"],
        image_path=row["image_path"],
        seen=row["seen"],
        outcome=row["outcome"],
    )


def _fts_match(query: str) -> str:
    words = [w for w in query.replace('"', " ").split() if w]
    if not words:
        return '""'
    return " OR ".join(f'"{w}"' for w in words)


class MemoryStore:
    """One persona's whole record, at `$SONAVIDA_HOME/personas/<persona-id>/memory.sqlite`."""

    def __init__(self, path: Path, *, mode: str = "rw") -> None:
        self.path = path
        if mode == "ro":
            if not path.is_file():
                raise FileNotFoundError(path)
            uri = f"file:{path.as_posix()}?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path)
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO inbox (id, experiences_acknowledged_through, "
                "erasures_acknowledged_through) VALUES (1, 0, 0)"
            )
            self._conn.commit()
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> MemoryStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def exists(path: Path) -> bool:
        return path.is_file()

    # -- self -----------------------------------------------------------------

    def write_self(
        self,
        *,
        persona_id: str,
        public_name: str,
        self_knowledge: dict[str, Any],
        born_at: datetime,
    ) -> None:
        self._conn.execute(
            "INSERT INTO self (persona_id, public_name, self_knowledge, born_at) "
            "VALUES (?, ?, ?, ?)",
            (persona_id, public_name, json.dumps(self_knowledge), _iso(born_at)),
        )
        self._conn.commit()

    def read_self(self) -> SelfRecord:
        row = self._conn.execute("SELECT * FROM self LIMIT 1").fetchone()
        if row is None:
            raise LookupError("no self record: this persona has not been born")
        return SelfRecord(
            persona_id=row["persona_id"],
            public_name=row["public_name"],
            self_knowledge=json.loads(row["self_knowledge"]),
            born_at=_parse(row["born_at"]),
            departed_at=_parse(row["departed_at"]) if row["departed_at"] else None,
        )

    def record_departure(self, at: datetime) -> None:
        self._conn.execute("UPDATE self SET departed_at = ?", (_iso(at),))
        self._conn.commit()

    # -- entries ----------------------------------------------------------------

    def append(
        self,
        *,
        at: datetime,
        kind: str,
        text: str,
        importance: int,
        reason: str | None = None,
        piece_id: str | None = None,
        visitor_pseudonym: str | None = None,
        visitor_name: str | None = None,
        source_sequence: int | None = None,
    ) -> int:
        if kind not in KINDS:
            raise ValueError(f"unknown entry kind: {kind!r}")
        if not 1 <= importance <= 5:
            raise ValueError(f"importance must be 1-5, got {importance!r}")
        cursor = self._conn.execute(
            "INSERT INTO entries "
            "(at, kind, text, reason, importance, piece_id, visitor_pseudonym, "
            "visitor_name, source_sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _iso(at),
                kind,
                text,
                reason,
                importance,
                piece_id,
                visitor_pseudonym,
                visitor_name,
                source_sequence,
            ),
        )
        self._conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def all_entries(self) -> list[Entry]:
        rows = self._conn.execute("SELECT * FROM entries ORDER BY id ASC").fetchall()
        return [_entry_from_row(r) for r in rows]

    def recall(self, query: str, *, budget: int = 20) -> list[Entry]:
        """The most relevant entries for `query`: match, then recency and importance."""
        rows: Iterable[sqlite3.Row] = ()
        if query.strip():
            rows = self._conn.execute(
                "SELECT e.* FROM entries_fts f "
                "JOIN entries e ON e.id = f.rowid "
                "WHERE entries_fts MATCH ? "
                "ORDER BY bm25(entries_fts) ASC, e.importance DESC, e.at DESC "
                "LIMIT ?",
                (_fts_match(query), budget),
            ).fetchall()
        entries = [_entry_from_row(r) for r in rows]
        if entries:
            return entries
        rows = self._conn.execute(
            "SELECT * FROM entries ORDER BY importance DESC, at DESC LIMIT ?", (budget,)
        ).fetchall()
        return [_entry_from_row(r) for r in rows]

    # -- pieces -------------------------------------------------------------------

    def create_piece(self, *, piece_id: str, intention_entry: int) -> None:
        self._conn.execute(
            "INSERT INTO pieces (id, intention_entry, state, suggested_labels) "
            "VALUES (?, ?, 'in-progress', '[]')",
            (piece_id, intention_entry),
        )
        self._conn.commit()

    def get_piece(self, piece_id: str) -> PieceRecord:
        row = self._conn.execute("SELECT * FROM pieces WHERE id = ?", (piece_id,)).fetchone()
        if row is None:
            raise LookupError(f"no such piece: {piece_id}")
        return _piece_from_row(row)

    def update_piece(
        self,
        piece_id: str,
        *,
        state: str | None = None,
        title: str | None = None,
        statement: str | None = None,
        suggested_labels: frozenset[str] | None = None,
        labels: frozenset[str] | None = None,
        image_path: str | None = None,
    ) -> None:
        if state is not None and state not in PIECE_STATES:
            raise ValueError(f"unknown piece state: {state!r}")
        fields: dict[str, Any] = {}
        if state is not None:
            fields["state"] = state
        if title is not None:
            fields["title"] = title
        if statement is not None:
            fields["statement"] = statement
        if suggested_labels is not None:
            fields["suggested_labels"] = json.dumps(sorted(suggested_labels))
        if labels is not None:
            fields["labels"] = json.dumps(sorted(labels))
        if image_path is not None:
            fields["image_path"] = image_path
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE pieces SET {assignments} WHERE id = ?",
            (*fields.values(), piece_id),
        )
        self._conn.commit()

    def pieces_in_state(self, *states: str) -> list[PieceRecord]:
        placeholders = ", ".join("?" for _ in states)
        rows = self._conn.execute(
            f"SELECT * FROM pieces WHERE state IN ({placeholders})",
            states,
        ).fetchall()
        return [_piece_from_row(r) for r in rows]

    # -- attempts -------------------------------------------------------------------

    def add_attempt(self, *, piece_id: str, asked: str, outcome: str = "discarded") -> int:
        if outcome not in ATTEMPT_OUTCOMES:
            raise ValueError(f"unknown attempt outcome: {outcome!r}")
        cursor = self._conn.execute(
            "INSERT INTO attempts (piece_id, asked, outcome) VALUES (?, ?, ?)",
            (piece_id, asked, outcome),
        )
        self._conn.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    def update_attempt(
        self,
        attempt_id: int,
        *,
        image_path: str | None = None,
        seen: str | None = None,
        outcome: str | None = None,
    ) -> None:
        if outcome is not None and outcome not in ATTEMPT_OUTCOMES:
            raise ValueError(f"unknown attempt outcome: {outcome!r}")
        fields: dict[str, Any] = {}
        if image_path is not None:
            fields["image_path"] = image_path
        if seen is not None:
            fields["seen"] = seen
        if outcome is not None:
            fields["outcome"] = outcome
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._conn.execute(
            f"UPDATE attempts SET {assignments} WHERE id = ?",
            (*fields.values(), attempt_id),
        )
        self._conn.commit()

    def attempts_for(self, piece_id: str) -> list[Attempt]:
        rows = self._conn.execute(
            "SELECT * FROM attempts WHERE piece_id = ? ORDER BY id ASC", (piece_id,)
        ).fetchall()
        return [_attempt_from_row(r) for r in rows]

    # -- inbox bookkeeping ------------------------------------------------------

    def experiences_acknowledged_through(self) -> int:
        row = self._conn.execute(
            "SELECT experiences_acknowledged_through FROM inbox WHERE id = 1"
        ).fetchone()
        return int(row[0])

    def set_experiences_acknowledged_through(self, sequence: int) -> None:
        self._conn.execute(
            "UPDATE inbox SET experiences_acknowledged_through = ? WHERE id = 1", (sequence,)
        )
        self._conn.commit()

    def erasures_acknowledged_through(self) -> int:
        row = self._conn.execute(
            "SELECT erasures_acknowledged_through FROM inbox WHERE id = 1"
        ).fetchone()
        return int(row[0])

    def set_erasures_acknowledged_through(self, sequence: int) -> None:
        self._conn.execute(
            "UPDATE inbox SET erasures_acknowledged_through = ? WHERE id = 1", (sequence,)
        )
        self._conn.commit()

    # -- used only by memory/erasure.py (R-8) ------------------------------------

    def connection(self) -> sqlite3.Connection:
        return self._conn
