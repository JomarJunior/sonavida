"""`do-nothing`: remembered as `chose-nothing`, forcing nothing (FR-015)."""

from __future__ import annotations

from datetime import datetime

from sonavida.memory.store import MemoryStore


def chose_nothing(*, store: MemoryStore, reason: str, importance: int, at: datetime) -> None:
    store.append(
        at=at,
        kind="chose-nothing",
        text="chose to do nothing.",
        reason=reason,
        importance=importance,
    )
