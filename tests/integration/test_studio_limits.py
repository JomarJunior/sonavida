"""T042: waits and interruptions are the persona's own life, never a lowered, retried
or replaced request (FR-029, FR-030, SC-007)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sonavida import birth
from sonavida.life import Life
from sonavida.ports.clock import SimulatedClock
from sonavida.ports.models import Busy, CannotServe, Failed, ModelOutcome, Starting, Stopping
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.models import ScriptedModels
from sonavida.standins.perception import ScriptedPerception
from sonavida.translate import translate
from sonavida.turns.proposals import valid_actions

from ..conftest import PELLAM_ID
from .conftest import StudioLinkAndState

FORBIDDEN_WORDS = (
    "model",
    "modelmora",
    "queue",
    "busy",
    "starting",
    "stopping",
    "failed_during_generation",
    "cannot_be_served_on_this_studio",
)
ASK = "a quiet harbor, dusk, low light, exactly as I described it"


def _reply(action: str, details: dict[str, object], reason: str, *, next_in: str = "PT1H") -> str:
    return json.dumps(
        {
            "action": action,
            "details": details,
            "reason": reason,
            "remember": {"importance": 3},
            "nextTurnIn": next_in,
        }
    )


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=9)


async def test_studio_limits_are_lived_not_crashed_and_the_ask_is_never_altered(
    tmp_path: Path,
    examples: Path,
    clock: SimulatedClock,
    studiolink_and_state: StudioLinkAndState,
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    store = birth.birth_synthetic(
        PELLAM_ID, examples / "pellam-quist.persona.yaml", home=home, clock=clock
    )
    models = ScriptedModels()
    life = Life(
        store=store,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )

    async def turn(
        action: str,
        details: dict[str, object],
        reason: str,
        image_outcome: ModelOutcome | None = None,
    ) -> None:
        if image_outcome is not None:
            models.script_image(image_outcome)
        models.script_text(_reply(action, details, reason))
        await life.take_turn()

    await turn("set-presence", {"presence": "in-the-studio"}, "time to work.")
    await turn("form-intention", {"intention": "a harbor at dusk"}, "the mood struck.")
    piece_id = life.state.working_on
    assert piece_id is not None

    await turn(
        "make-attempt", {"ask": ASK}, "trying it.", Busy(retry_at=clock.now() + timedelta(hours=1))
    )
    assert life.state.working_on == piece_id  # busy: still here, free to try again

    await turn(
        "make-attempt",
        {"ask": ASK},
        "trying again, exactly the same idea.",
        Starting(retry_at=clock.now() + timedelta(minutes=30)),
    )
    assert life.state.working_on == piece_id  # starting: same, still here

    await turn("make-attempt", {"ask": ASK}, "once more.", Stopping())
    assert life.state.interrupted_piece == piece_id
    assert life.state.working_on is None
    assert "continue-unfinished" in valid_actions(life.state)

    await turn("continue-unfinished", {"piece": piece_id}, "picking it back up.")
    assert life.state.working_on == piece_id
    assert life.state.interrupted_piece is None

    await turn("make-attempt", {"ask": ASK}, "trying yet again.", Failed())
    await turn("do-nothing", {}, "resting after all that.")

    kinds = [e.kind for e in store.all_entries()]
    assert "studio-not-ready" in kinds
    assert "interrupted" in kinds
    assert "attempt-failed" in kinds

    for entry in store.all_entries():
        if entry.kind in ("studio-not-ready", "interrupted", "attempt-failed"):
            lowered = entry.text.lower()
            for word in FORBIDDEN_WORDS:
                assert word not in lowered

    # every attempt carried exactly the same `ask`, verbatim — never lowered, retried
    # or replaced by SonaVida itself (FR-029). Four attempts were made in total.
    image_calls = [call for kind, call in models.calls if kind == "image"]
    assert len(image_calls) == 4
    assert all(ASK in call for call in image_calls)


def test_cannot_serve_translates_to_attempt_failed_same_as_failed() -> None:
    assert translate(CannotServe()).kind == "attempt-failed"
    assert translate(Failed()).kind == "attempt-failed"
