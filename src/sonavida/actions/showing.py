"""Showing work: `keep` or `submit` a finished piece, each with its reason (FR-017)."""

from __future__ import annotations

from datetime import datetime

from sonavida.memory.store import MemoryStore


def keep(*, store: MemoryStore, piece_id: str, reason: str, importance: int, at: datetime) -> None:
    store.update_piece(piece_id, state="kept")
    store.append(
        at=at,
        kind="kept",
        text="kept the piece.",
        reason=reason,
        importance=importance,
        piece_id=piece_id,
    )


def submit(
    *,
    store: MemoryStore,
    piece_id: str,
    suggested_labels: frozenset[str],
    reason: str,
    importance: int,
    at: datetime,
) -> None:
    store.update_piece(piece_id, state="submitted", suggested_labels=suggested_labels)
    store.append(
        at=at,
        kind="submitted",
        text="submitted the piece.",
        reason=reason,
        importance=importance,
        piece_id=piece_id,
    )
