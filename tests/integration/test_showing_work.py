"""T029: only submitted, accepted pieces ever reach the Studio Link (SC-004, FR-018,
FR-020, FR-042)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida.actions import creation, showing
from sonavida.memory.store import MemoryStore
from sonavida.ports.gate import Verdict
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.models import ScriptedModels
from sonavida.standins.perception import ScriptedPerception

from .conftest import StudioLinkAndState

PERSONA_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    s = MemoryStore(tmp_path / "memory.sqlite")
    s.write_self(
        persona_id=str(PERSONA_ID), public_name="Pellam Quist", self_knowledge={}, born_at=_now()
    )
    return s


async def _finished_piece(store: MemoryStore, piece_dir: Path, models: ScriptedModels) -> str:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    attempt_id, _ = await creation.make_attempt(
        store=store,
        models=models,
        self_knowledge={},
        piece_dir=piece_dir,
        piece_id=piece_id,
        ask="a harbor",
        reason="why not.",
        importance=2,
        at=_now(),
    )
    creation.finish(
        store=store,
        piece_id=piece_id,
        attempt_id=attempt_id,
        title="Harbor",
        statement="A quiet harbor.",
        reason="it's done.",
        importance=3,
        at=_now(),
    )
    return piece_id


async def test_kept_pieces_never_reach_the_studio_link(
    store: MemoryStore, tmp_path: Path, studiolink_and_state: StudioLinkAndState
) -> None:
    _studiolink, state = studiolink_and_state
    piece_id = await _finished_piece(store, tmp_path / "pieces" / "p1", ScriptedModels())
    showing.keep(store=store, piece_id=piece_id, reason="staying with me.", importance=2, at=_now())
    assert store.get_piece(piece_id).state == "kept"
    assert not state.pieces


async def test_abandoned_pieces_never_reach_the_studio_link(
    store: MemoryStore, tmp_path: Path, studiolink_and_state: StudioLinkAndState
) -> None:
    _studiolink, state = studiolink_and_state
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why.", importance=2, at=_now()
    )
    creation.abandon(store=store, piece_id=piece_id, reason="gave up.", importance=1, at=_now())
    assert not state.pieces


async def test_only_submitted_pieces_reach_the_gate_and_accepted_ones_reach_studiolink(
    store: MemoryStore, tmp_path: Path, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    piece_id = await _finished_piece(store, tmp_path / "pieces" / "p2", ScriptedModels())
    showing.submit(
        store=store,
        piece_id=piece_id,
        suggested_labels=frozenset({"explicit"}),
        reason="ready to show it.",
        importance=3,
        at=_now(),
    )
    piece = store.get_piece(piece_id)
    assert piece.state == "submitted"
    assert piece.suggested_labels == frozenset({"explicit"})

    gate = ScriptedGate(studiolink, is_reference_standin=True)
    gate.script(
        Verdict(accepted=True, reason="fits the museum.", labels=frozenset({"explicit", "violent"}))
    )
    perception = ScriptedPerception()
    perception.script("a harbor scene.")

    assert piece.image_path is not None
    assert piece.title is not None
    assert piece.statement is not None
    image_bytes = Path(piece.image_path).read_bytes()
    neutral_description = await perception.describe(image_bytes)
    verdict = await gate.submit(
        persona_id=PERSONA_ID,
        public_name="Pellam Quist",
        piece_id=uuid.UUID(piece_id),
        title=piece.title,
        statement=piece.statement,
        image_bytes=image_bytes,
        neutral_description=neutral_description,
        suggested_labels=piece.suggested_labels,
    )
    assert verdict.accepted
    assert uuid.UUID(piece_id) in state.pieces
    candidate = state.pieces[uuid.UUID(piece_id)]
    assert candidate.title == "Harbor"
    assert candidate.statement == "A quiet harbor."
    # the gate may add labels the persona did not suggest; the persona cannot remove them.
    assert set(candidate.labels) == {"explicit", "violence"}


async def test_a_rejected_piece_never_reaches_studiolink_and_comes_back_with_feedback(
    store: MemoryStore, tmp_path: Path, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    piece_id = await _finished_piece(store, tmp_path / "pieces" / "p3", ScriptedModels())
    showing.submit(
        store=store,
        piece_id=piece_id,
        suggested_labels=frozenset(),
        reason="ready.",
        importance=2,
        at=_now(),
    )
    gate = ScriptedGate(studiolink, is_reference_standin=True)
    gate.script(
        Verdict(
            accepted=False,
            reason="does not fit the museum right now.",
            labels=frozenset(),
            feedback="try a wider view.",
        )
    )
    piece = store.get_piece(piece_id)
    assert piece.image_path is not None
    assert piece.title is not None
    assert piece.statement is not None
    image_bytes = Path(piece.image_path).read_bytes()
    verdict = await gate.submit(
        persona_id=PERSONA_ID,
        public_name="Pellam Quist",
        piece_id=uuid.UUID(piece_id),
        title=piece.title,
        statement=piece.statement,
        image_bytes=image_bytes,
        neutral_description="a harbor.",
        suggested_labels=piece.suggested_labels,
    )
    assert not verdict.accepted
    assert not state.pieces

    store.update_piece(piece_id, state="rejected", labels=verdict.labels)
    store.append(
        at=_now(),
        kind="verdict",
        text=verdict.feedback or "rejected.",
        reason=verdict.reason,
        importance=2,
        piece_id=piece_id,
    )
    verdict_entries = [e for e in store.all_entries() if e.kind == "verdict"]
    assert verdict_entries[-1].text == "try a wider view."
    assert store.get_piece(piece_id).state == "rejected"
