"""T035: an erasure notice removes a visitor's identity, never the memories that hold
it (R-8, FR-032, FR-033, SC-006)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida import inbox
from sonavida.memory.erasure import erase_visitor
from sonavida.memory.store import MemoryStore
from sonavida.memory.tokens import token_for

from ..conftest import StudioLinkAndState

PERSONA_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")
PIECE_ID = uuid.uuid4()


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    s = MemoryStore(tmp_path / "memory.sqlite")
    s.write_self(
        persona_id=str(PERSONA_ID), public_name="Pellam Quist", self_knowledge={}, born_at=_now()
    )
    return s


async def test_erasure_clears_both_visitor_columns_and_replaces_the_token(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await state.seed_exhibited_piece(
        piece_id=PIECE_ID,
        persona_id=PERSONA_ID,
        public_name="Pellam Quist",
        title="Harbor",
        statement="A quiet harbor.",
        neutral_description="a harbor scene.",
    )
    state.add_visitor("visitor-a", "Marisol")
    await state.script_comment(
        piece_id=PIECE_ID, visitor_id="visitor-a", text="I love the light here."
    )
    await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())

    entry = next(e for e in store.all_entries() if e.kind == "experience")
    pseudonym = entry.visitor_pseudonym
    assert pseudonym is not None
    assert entry.visitor_name == "Marisol"
    assert token_for(pseudonym) in entry.text

    await state.erase_visitor("visitor-a")
    collected = await inbox.collect_erasure_notices(store, studiolink, PERSONA_ID)
    assert collected == 1

    erased = next(e for e in store.all_entries() if e.kind == "experience")
    assert erased.visitor_pseudonym is None
    assert erased.visitor_name is None
    assert token_for(pseudonym) not in erased.text
    assert "Marisol" not in erased.text
    assert "someone" in erased.text
    # the memory itself remains.
    assert "I love the light here." in erased.text


async def test_a_free_typed_display_name_is_also_scrubbed(store: MemoryStore) -> None:
    now = _now()
    pseudonym = "v-abcdefghijklmnopqrst"
    entry_id = store.append(
        at=now,
        kind="experience",
        text=f"{token_for(pseudonym)} commented: Hi, I'm Marisol and I loved this!",
        importance=2,
        piece_id=str(PIECE_ID),
        visitor_pseudonym=pseudonym,
        visitor_name="Marisol",
    )
    erase_visitor(store, pseudonym)
    entry = next(e for e in store.all_entries() if e.id == entry_id)
    assert "Marisol" not in entry.text
    assert "marisol" not in entry.text.lower()
    assert "someone" in entry.text


def test_the_notice_is_acknowledged_only_after_erasure_and_is_never_a_memory(
    store: MemoryStore,
) -> None:
    now = _now()
    pseudonym = "v-abcdefghijklmnopqrst"
    store.append(
        at=now,
        kind="experience",
        text=f"{token_for(pseudonym)} commented: hello.",
        importance=2,
        visitor_pseudonym=pseudonym,
        visitor_name="Marisol",
    )
    before = len(store.all_entries())
    erase_visitor(store, pseudonym)
    after = store.all_entries()
    # no new entry was created for the notice itself.
    assert len(after) == before
    assert all(e.kind != "erasure" for e in after)


def test_pieces_are_untouched_by_erasure(store: MemoryStore) -> None:
    from sonavida.actions import creation

    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    pseudonym = "v-abcdefghijklmnopqrst"
    store.append(
        at=_now(),
        kind="experience",
        text=f"{token_for(pseudonym)} commented on it.",
        importance=2,
        piece_id=piece_id,
        visitor_pseudonym=pseudonym,
        visitor_name="Marisol",
    )
    before = store.get_piece(piece_id)
    erase_visitor(store, pseudonym)
    after = store.get_piece(piece_id)
    assert before == after


def test_no_fragment_of_the_pseudonym_or_name_survives_in_the_raw_file_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.sqlite"
    store = MemoryStore(path)
    store.write_self(
        persona_id=str(PERSONA_ID), public_name="Pellam Quist", self_knowledge={}, born_at=_now()
    )
    pseudonym = "v-abcdefghijklmnopqrst"
    display_name = "Zzyzxquill"  # distinctive, unlikely to collide with anything else on disk
    for i in range(5):
        store.append(
            at=_now(),
            kind="experience",
            text=f"{token_for(pseudonym)} commented: hello number {i}, {display_name} here.",
            importance=2,
            visitor_pseudonym=pseudonym,
            visitor_name=display_name,
        )
    erase_visitor(store, pseudonym)
    store.close()

    raw = path.read_bytes()
    assert pseudonym.encode() not in raw
    assert display_name.encode() not in raw
    assert display_name.lower().encode() not in raw
