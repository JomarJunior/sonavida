"""T025: creation actions record their own entries; image requests carry only the
persona's own words (FR-011); piece state moves only along the data-model transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida.actions import creation
from sonavida.memory.store import MemoryStore
from sonavida.ports.models import CannotServe, Stopping
from sonavida.standins.models import TINY_PNG, ScriptedModels
from sonavida.standins.perception import ScriptedPerception

SELF_KNOWLEDGE = {
    "stylesAndMedia": "loose watercolor washes, muted greens and greys.",
    "craft": "wide horizontal formats, rough unfinished edges.",
}


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.sqlite")


@pytest.fixture
def piece_dir(tmp_path: Path) -> Path:
    return tmp_path / "pieces" / "piece-1"


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def test_build_image_description_carries_the_ask_verbatim() -> None:
    ask = "a harbor at dusk, the tide going out"
    description = creation.build_image_description(ask, SELF_KNOWLEDGE)
    assert ask in description


def test_build_image_description_adds_only_craft_and_styles_words() -> None:
    ask = "a harbor at dusk"
    description = creation.build_image_description(ask, SELF_KNOWLEDGE)
    allowed_words = set(
        (ask + " " + SELF_KNOWLEDGE["stylesAndMedia"] + " " + SELF_KNOWLEDGE["craft"]).split()
    )
    for word in description.split():
        assert word in allowed_words, f"unexpected word not from the persona's own words: {word!r}"


def test_build_image_description_without_craft_or_styles_is_only_the_ask() -> None:
    ask = "a lighthouse in fog"
    assert creation.build_image_description(ask, {}) == ask


def test_form_intention_records_entry_and_creates_piece(store: MemoryStore) -> None:
    piece_id = creation.form_intention(
        store=store,
        intention="a harbor at dusk",
        reason="the fog reminded me of home.",
        importance=3,
        at=_now(),
    )
    entries = store.all_entries()
    assert entries[-1].kind == "intention"
    assert entries[-1].text == "a harbor at dusk"
    assert entries[-1].reason == "the fog reminded me of home."
    piece = store.get_piece(piece_id)
    assert piece.state == "in-progress"
    assert piece.intention_entry == entries[-1].id


async def test_make_attempt_succeeds_and_is_kept_as_final(
    store: MemoryStore, piece_dir: Path
) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    models = ScriptedModels()
    _attempt_id, failure = await creation.make_attempt(
        store=store,
        models=models,
        self_knowledge=SELF_KNOWLEDGE,
        piece_dir=piece_dir,
        piece_id=piece_id,
        ask="a harbor at dusk",
        reason="trying the light.",
        importance=3,
        at=_now(),
    )
    assert failure is None
    attempts = store.attempts_for(piece_id)
    assert len(attempts) == 1
    assert attempts[0].outcome == "kept-as-final"
    assert attempts[0].image_path is not None
    assert Path(attempts[0].image_path).read_bytes() == TINY_PNG
    entries = [e for e in store.all_entries() if e.kind == "attempt"]
    assert entries[-1].text == "a harbor at dusk"
    assert entries[-1].reason == "trying the light."
    # the request carried to Models is the built description, not a runtime invention.
    kind, description = models.calls[-1]
    assert kind == "image"
    assert "a harbor at dusk" in description


async def test_make_attempt_studio_not_ready_leaves_no_image(
    store: MemoryStore, piece_dir: Path
) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    models = ScriptedModels()
    models.script_image(CannotServe())
    _attempt_id, failure = await creation.make_attempt(
        store=store,
        models=models,
        self_knowledge=SELF_KNOWLEDGE,
        piece_dir=piece_dir,
        piece_id=piece_id,
        ask="a harbor",
        reason="why not.",
        importance=2,
        at=_now(),
    )
    assert isinstance(failure, CannotServe)
    attempt = store.attempts_for(piece_id)[0]
    assert attempt.outcome == "did-not-come-out"
    assert attempt.image_path is None


async def test_make_attempt_interrupted_by_stopping(store: MemoryStore, piece_dir: Path) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    models = ScriptedModels()
    models.script_image(Stopping())
    _attempt_id, failure = await creation.make_attempt(
        store=store,
        models=models,
        self_knowledge=SELF_KNOWLEDGE,
        piece_dir=piece_dir,
        piece_id=piece_id,
        ask="a harbor",
        reason="why not.",
        importance=2,
        at=_now(),
    )
    assert isinstance(failure, Stopping)
    attempt = store.attempts_for(piece_id)[0]
    assert attempt.outcome == "interrupted"


async def test_look_again_records_perception_and_updates_the_attempt(
    store: MemoryStore, piece_dir: Path
) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    models = ScriptedModels()
    attempt_id, _ = await creation.make_attempt(
        store=store,
        models=models,
        self_knowledge=SELF_KNOWLEDGE,
        piece_dir=piece_dir,
        piece_id=piece_id,
        ask="a harbor",
        reason="why not.",
        importance=2,
        at=_now(),
    )
    perception = ScriptedPerception()
    perception.script("a grey harbor under low cloud.")
    description = await creation.look_again(
        store=store,
        perception=perception,
        piece_id=piece_id,
        attempt_id=attempt_id,
        reason="looking closer.",
        importance=2,
        at=_now(),
    )
    assert description == "a grey harbor under low cloud."
    attempt = store.attempts_for(piece_id)[0]
    assert attempt.seen == "a grey harbor under low cloud."
    seen_entries = [e for e in store.all_entries() if e.kind == "attempt-seen"]
    assert seen_entries[-1].text == "a grey harbor under low cloud."
    assert seen_entries[-1].reason == "looking closer."


async def test_rework_marks_old_attempt_reworked_and_makes_a_new_one(
    store: MemoryStore, piece_dir: Path
) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    models = ScriptedModels()
    first_id, _ = await creation.make_attempt(
        store=store,
        models=models,
        self_knowledge=SELF_KNOWLEDGE,
        piece_dir=piece_dir,
        piece_id=piece_id,
        ask="a harbor",
        reason="why not.",
        importance=2,
        at=_now(),
    )
    second_id, failure = await creation.rework(
        store=store,
        models=models,
        self_knowledge=SELF_KNOWLEDGE,
        piece_dir=piece_dir,
        piece_id=piece_id,
        old_attempt_id=first_id,
        ask="a harbor, more fog",
        reason="wanted more fog.",
        importance=2,
        at=_now(),
    )
    assert failure is None
    attempts = {a.id: a for a in store.attempts_for(piece_id)}
    assert attempts[first_id].outcome == "reworked"
    assert attempts[second_id].outcome == "kept-as-final"


def test_finish_requires_kept_attempt_sets_title_and_statement(
    store: MemoryStore, piece_dir: Path
) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    attempt_id = store.add_attempt(piece_id=piece_id, asked="a harbor", outcome="kept-as-final")
    store.update_attempt(attempt_id, image_path=str(piece_dir / "attempt-1.png"))
    piece_dir.mkdir(parents=True, exist_ok=True)
    (piece_dir / "attempt-1.png").write_bytes(TINY_PNG)

    creation.finish(
        store=store,
        piece_id=piece_id,
        attempt_id=attempt_id,
        title="Harbor",
        statement="A quiet harbor at dusk.",
        reason="it says what I meant.",
        importance=4,
        at=_now(),
    )
    piece = store.get_piece(piece_id)
    assert piece.state == "finished"
    assert piece.title == "Harbor"
    assert piece.statement == "A quiet harbor at dusk."
    assert piece.image_path == str(piece_dir / "attempt-1.png")
    entries = [e for e in store.all_entries() if e.kind == "finished"]
    assert entries[-1].text == "Harbor"
    assert entries[-1].reason == "it says what I meant."


def test_abandon_records_reason_and_sets_state(store: MemoryStore) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why not.", importance=2, at=_now()
    )
    creation.abandon(
        store=store, piece_id=piece_id, reason="it wasn't working.", importance=2, at=_now()
    )
    piece = store.get_piece(piece_id)
    assert piece.state == "abandoned"
    entries = [e for e in store.all_entries() if e.kind == "abandoned"]
    assert entries[-1].reason == "it wasn't working."


def test_piece_state_moves_only_forward(store: MemoryStore) -> None:
    piece_id = creation.form_intention(
        store=store, intention="a harbor", reason="why.", importance=2, at=_now()
    )
    assert store.get_piece(piece_id).state == "in-progress"
    creation.abandon(
        store=store, piece_id=piece_id, reason="done with it.", importance=1, at=_now()
    )
    assert store.get_piece(piece_id).state == "abandoned"
