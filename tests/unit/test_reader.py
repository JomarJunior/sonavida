"""T040: `memory/reader.py` renders plain language, each decision beside its reason,
and visitors by name or "someone" — never a raw pseudonym (R-8, R-12)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida.memory import reader
from sonavida.memory.store import MemoryStore
from sonavida.memory.tokens import token_for


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def path(tmp_path: Path) -> Path:
    memory_path = tmp_path / "memory.sqlite"
    store = MemoryStore(memory_path)
    store.write_self(persona_id="p1", public_name="Pellam Quist", self_knowledge={}, born_at=_now())
    store.append(
        at=_now(),
        kind="presence",
        text="in-the-studio",
        reason="the evening light called me in.",
        importance=2,
    )
    pseudonym = "v-abcdefghijklmnopqrst"
    store.append(
        at=_now(),
        kind="experience",
        text=f"{token_for(pseudonym)} commented: what a quiet harbor.",
        importance=2,
        visitor_pseudonym=pseudonym,
        visitor_name="Marisol",
    )
    store.close()
    return memory_path


def test_each_decision_is_printed_beside_its_reason(path: Path) -> None:
    lines = [e.line for e in reader.read_memory(path)]
    presence_line = next(line for line in lines if "presence changed to" in line)
    assert "in-the-studio" in presence_line
    assert "because the evening light called me in." in presence_line


def test_visitors_are_rendered_by_name_never_a_raw_pseudonym(path: Path) -> None:
    lines = [e.line for e in reader.read_memory(path)]
    experience_line = next(line for line in lines if "commented" in line)
    assert "Marisol" in experience_line
    assert "v-abcdefghijklmnopqrst" not in experience_line
    assert "⟨v:" not in experience_line


def test_entries_are_read_in_time_order(path: Path) -> None:
    entries = reader.read_memory(path)
    assert entries == sorted(entries, key=lambda e: e.at)


def test_from_and_to_dates_filter_the_range(tmp_path: Path) -> None:
    memory_path = tmp_path / "memory.sqlite"
    store = MemoryStore(memory_path)
    store.write_self(persona_id="p1", public_name="Pellam Quist", self_knowledge={}, born_at=_now())
    store.append(
        at=datetime(2026, 1, 1, tzinfo=UTC), kind="chose-nothing", text="day one.", importance=1
    )
    store.append(
        at=datetime(2026, 1, 10, tzinfo=UTC), kind="chose-nothing", text="day ten.", importance=1
    )
    store.close()

    from datetime import date

    only_early = reader.read_memory(memory_path, until=date(2026, 1, 5))
    assert len(only_early) == 1
    assert "day one." in only_early[0].line

    only_late = reader.read_memory(memory_path, since=date(2026, 1, 5))
    assert len(only_late) == 1
    assert "day ten." in only_late[0].line
