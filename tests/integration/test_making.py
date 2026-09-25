"""T028: a simulated waking period produces finished pieces with intention, attempts,
what was seen, a title and a statement, and an abandoned piece with its reason;
choosing not to work is allowed and remembered (FR-015)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sonavida import birth
from sonavida.ports.clock import SimulatedClock
from sonavida.runtime import Runtime
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.models import ScriptedModels
from sonavida.standins.perception import ScriptedPerception

from ..conftest import PELLAM_ID
from .conftest import StudioLinkAndState


def _reply(action: str, details: dict[str, object], reason: str, *, next_in: str = "PT2H") -> str:
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
    return SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=2)


async def test_a_waking_period_finishes_a_piece_and_abandons_another(
    tmp_path: Path,
    examples: Path,
    clock: SimulatedClock,
    studiolink_and_state: StudioLinkAndState,
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    path = examples / "pellam-quist.persona.yaml"
    store = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)

    models = ScriptedModels()
    models.script_text(
        _reply("set-presence", {"presence": "in-the-studio"}, "the evening called me in."),
        _reply("form-intention", {"intention": "a harbor at dusk"}, "the light was right."),
        _reply(
            "make-attempt", {"ask": "a quiet harbor, dusk, low light"}, "trying the first idea."
        ),
        _reply("look-again", {"attempt": "1"}, "wanting to see it clearly."),
        _reply(
            "finish",
            {"attempt": "1", "title": "Harbor", "statement": "A quiet harbor at dusk."},
            "it says what I meant.",
        ),
        _reply("form-intention", {"intention": "a storm over the sea"}, "the mood shifted."),
        _reply("make-attempt", {"ask": "a storm over grey water"}, "trying it."),
        _reply("abandon", {}, "it wasn't coming together."),
        _reply("do-nothing", {}, "resting from the work."),
    )
    perception = ScriptedPerception()
    perception.script("a grey harbor with a low warm light on the water.")

    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=perception,
        gate=ScriptedGate(studiolink),
    )
    runtime.host(store, PELLAM_ID)

    clock.join()
    await clock.wait_until(clock.now() + timedelta(days=1))
    clock.leave()
    await runtime.shutdown()

    pieces = store.pieces_in_state("finished") + store.pieces_in_state("abandoned")
    assert len(pieces) == 2
    finished = next(p for p in pieces if p.state == "finished")
    abandoned = next(p for p in pieces if p.state == "abandoned")

    assert finished.title == "Harbor"
    assert finished.statement == "A quiet harbor at dusk."
    attempts = store.attempts_for(finished.id)
    assert attempts[0].asked == "a quiet harbor, dusk, low light"
    assert attempts[0].seen == "a grey harbor with a low warm light on the water."

    kinds = [e.kind for e in store.all_entries()]
    assert "intention" in kinds
    assert "attempt" in kinds
    assert "attempt-seen" in kinds
    assert "finished" in kinds
    assert "abandoned" in kinds
    assert "chose-nothing" in kinds

    abandoned_entry = next(e for e in store.all_entries() if e.kind == "abandoned")
    assert abandoned_entry.reason == "it wasn't coming together."
    assert abandoned_entry.piece_id == abandoned.id
