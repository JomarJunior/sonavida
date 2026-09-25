"""T033: experiences arrive one by one, in order, acknowledged only once stored; a
visitor met before is recognized; a refused message leaves no trace; a human-gate
outcome moves the piece and becomes a memory (SC-005, FR-022 to FR-024, FR-028)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from miraveja_studiolink.standin.state import StandInState

from sonavida import inbox
from sonavida.memory.store import MemoryStore

from .conftest import StudioLinkAndState

PERSONA_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")
PIECE_ID = uuid.uuid4()
HUB_CONTAMINATED_EXAMPLE = Path(
    "specs/001-studiolink-contract/contracts/examples/invalid/experience-batch-with-count.json"
)


def _hub_path() -> Path:
    env = os.environ.get("MIRAVEJA_HUB_PATH")
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[4])
    for base in candidates:
        path = base / HUB_CONTAMINATED_EXAMPLE
        if path.is_file():
            return path
    pytest.skip("hub checkout not found; set MIRAVEJA_HUB_PATH")


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    s = MemoryStore(tmp_path / "memory.sqlite")
    s.write_self(
        persona_id=str(PERSONA_ID), public_name="Pellam Quist", self_knowledge={}, born_at=_now()
    )
    return s


async def _seed_piece(state: StandInState) -> None:
    await state.seed_exhibited_piece(
        piece_id=PIECE_ID,
        persona_id=PERSONA_ID,
        public_name="Pellam Quist",
        title="Harbor",
        statement="A quiet harbor.",
        neutral_description="a harbor scene.",
    )
    state.add_visitor("visitor-a", "Marisol")
    state.add_visitor("visitor-b", "Deniz")


async def test_experiences_are_stored_once_each_in_order_and_acknowledged_only_after(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await _seed_piece(state)
    await state.script_comment(
        piece_id=PIECE_ID, visitor_id="visitor-a", text="I love the light here."
    )
    await state.script_reaction(piece_id=PIECE_ID, visitor_id="visitor-a", reaction="love")
    await state.script_comment(
        piece_id=PIECE_ID, visitor_id="visitor-b", text="Reminds me of home."
    )

    collected = await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())
    assert collected == 3

    entries = [e for e in store.all_entries() if e.kind == "experience"]
    assert len(entries) == 3
    assert "I love the light here." in entries[0].text
    assert "reacted with love" in entries[1].text
    assert "Reminds me of home." in entries[2].text
    assert store.experiences_acknowledged_through() == 3


async def test_nothing_is_lost_or_repeated_across_a_restart(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await _seed_piece(state)
    await state.script_reaction(piece_id=PIECE_ID, visitor_id="visitor-a", reaction="wonder")
    await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())

    await state.script_reaction(piece_id=PIECE_ID, visitor_id="visitor-a", reaction="laugh")
    # A second, independent collection call — as a restart would make — must not
    # repeat the first experience nor lose the second.
    await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())

    entries = [e for e in store.all_entries() if e.kind == "experience"]
    assert len(entries) == 2


async def test_a_visitor_met_before_is_recognized_by_pseudonym_and_name(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await _seed_piece(state)
    await state.script_comment(piece_id=PIECE_ID, visitor_id="visitor-a", text="First time here.")
    await state.script_comment(piece_id=PIECE_ID, visitor_id="visitor-a", text="Back again!")
    await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())

    entries = [e for e in store.all_entries() if e.kind == "experience"]
    assert entries[0].visitor_pseudonym == entries[1].visitor_pseudonym
    assert entries[0].visitor_name == entries[1].visitor_name


async def test_a_refused_message_leaves_no_trace(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await _seed_piece(state)
    contaminated = json.loads(_hub_path().read_text(encoding="utf-8"))
    contaminated = {k: v for k, v in contaminated.items() if not k.startswith("_")}
    state.force_response("collectExperiences", contaminated)

    collected = await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())
    assert collected == 0
    assert store.all_entries() == []
    assert store.experiences_acknowledged_through() == 0


async def test_a_human_gate_outcome_moves_the_piece_and_becomes_a_memory(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await _seed_piece(state)
    store.create_piece(piece_id=str(PIECE_ID), intention_entry=1)
    store.update_piece(str(PIECE_ID), state="accepted")

    await state.simulate_gate_outcome(PIECE_ID, "taken_down", "it broke a museum rule after all.")
    await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())

    piece = store.get_piece(str(PIECE_ID))
    assert piece.state == "taken-down"
    entries = [e for e in store.all_entries() if e.kind == "experience"]
    assert entries[-1].text == "it broke a museum rule after all."
    assert entries[-1].piece_id == str(PIECE_ID)
