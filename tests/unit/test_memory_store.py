"""T010: entries are append-only, importance and kind are checked, recall works."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida.memory.store import MemoryStore


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.sqlite")


def test_entry_ids_are_monotonic(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    first = store.append(at=now, kind="chose-nothing", text="a quiet morning.", importance=1)
    second = store.append(at=now, kind="chose-nothing", text="another quiet one.", importance=1)
    assert second == first + 1


@pytest.mark.parametrize("importance", [0, 6, -1])
def test_importance_must_be_1_to_5(store: MemoryStore, importance: int) -> None:
    with pytest.raises(ValueError, match="importance"):
        store.append(at=datetime.now(UTC), kind="chose-nothing", text="x", importance=importance)


def test_kind_is_restricted_to_the_data_model_list(store: MemoryStore) -> None:
    with pytest.raises(ValueError, match="kind"):
        store.append(at=datetime.now(UTC), kind="not-a-real-kind", text="x", importance=1)


def test_nothing_deletes_a_row(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    store.append(at=now, kind="chose-nothing", text="one.", importance=1)
    store.append(at=now, kind="chose-nothing", text="two.", importance=1)
    assert len(store.all_entries()) == 2
    assert not hasattr(store, "delete")
    assert not hasattr(store, "delete_entry")


def test_recall_returns_relevant_entries_by_match_recency_and_importance(
    store: MemoryStore,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    store.append(at=base, kind="intention", text="a harbor at dusk, low light.", importance=2)
    store.append(
        at=base.replace(day=2),
        kind="intention",
        text="a harbor at dawn, quiet light.",
        importance=5,
    )
    store.append(at=base.replace(day=3), kind="chose-nothing", text="rested all day.", importance=1)

    recalled = store.recall("harbor light", budget=10)
    texts = [e.text for e in recalled]
    assert "a harbor at dawn, quiet light." in texts
    assert "a harbor at dusk, low light." in texts
    assert "rested all day." not in texts
    # the more important, more recent harbor entry ranks first
    assert texts.index("a harbor at dawn, quiet light.") < texts.index(
        "a harbor at dusk, low light."
    )


def test_recall_respects_the_budget(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    for i in range(10):
        store.append(at=now, kind="chose-nothing", text=f"day {i} was quiet.", importance=1)
    assert len(store.recall("quiet", budget=3)) == 3


def test_recall_falls_back_to_recency_when_nothing_matches(store: MemoryStore) -> None:
    now = datetime.now(UTC)
    store.append(at=now, kind="chose-nothing", text="painted a harbor.", importance=3)
    recalled = store.recall("a word that appears nowhere at all", budget=5)
    assert len(recalled) == 1
