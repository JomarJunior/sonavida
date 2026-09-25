"""T048: a seeded simulated week of the Pellam example finishes at least one piece
under the 5 minute performance budget (SC-001 mechanics, plan performance goal); a
second, different synthetic definition comes alive with zero code change (SC-009)."""

from __future__ import annotations

import json
import time
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

WREN_ID = "00000000-0000-4000-8000-00000000a091"

# A synthetic definition unlike Pellam or Ivo in every tendency: a sculptor working in
# short daytime bursts rather than a painter who rests at dusk, to prove SC-009 needs
# no per-persona code — only a definition.
WREN_DEFINITION = f"""\
miravejaPersona: 1
nature: synthetic

identity:
  id: {WREN_ID}
  publicName: Wren Talbot
  about: |
    A synthetic test persona, a sculptor of driftwood forms, made only for spec
    004 tests. Belongs to no resident persona.
  openlyAI: true

taste:
  drawnTo: |
    Salvaged wood, rope, the shapes the sea leaves behind.
  themes:
    - driftwood forms
  stylesAndMedia: |
    Assembled, textured, unpainted surfaces.

voice:
  speech: |
    Blunt, practical, few words.
  temperament: |
    Impatient with talk, patient with material.

tendencies:
  presence: |
    Tends to be in the studio at midday and rest by evening.
  work: |
    Works in short bursts, often sets a piece aside unfinished.

cares:
  - the texture of found material

seedMemories:
  - id: first-driftwood
    when: as a young persona
    happened: |
      I found a length of grey driftwood shaped like a wave and knew I had to
      build from it, not against it.
"""


def _reply(action: str, details: dict[str, object], reason: str, *, next_in: str = "PT4H") -> str:
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
    return SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=13)


async def test_a_seeded_simulated_week_of_pellam_finishes_a_piece_under_5_minutes(
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
    models.script_text(
        _reply("set-presence", {"presence": "in-the-studio"}, "the evening light called me in."),
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
        # after finishing, the rest of the week falls through to the scripted
        # model's own default ("do-nothing"); a persona need not work every turn.
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

    started = time.monotonic()
    clock.join()
    await clock.wait_until(clock.now() + timedelta(days=7))
    clock.leave()
    await runtime.shutdown()
    elapsed = time.monotonic() - started
    assert elapsed < 300, f"a simulated week took {elapsed:.1f}s, over the 5 minute budget"

    finished = store.pieces_in_state("finished")
    assert len(finished) >= 1
    assert finished[0].title == "Harbor"


async def test_a_second_different_synthetic_definition_comes_alive_with_zero_code_change(
    tmp_path: Path,
    clock: SimulatedClock,
    studiolink_and_state: StudioLinkAndState,
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    wren_path = tmp_path / "wren.persona.yaml"
    wren_path.write_text(WREN_DEFINITION, encoding="utf-8")
    store = birth.birth_synthetic(WREN_ID, wren_path, home=home, clock=clock)
    born_entries = len(store.all_entries())

    models = ScriptedModels()
    models.script_text(
        _reply("set-presence", {"presence": "in-the-studio"}, "midday, time to build."),
        _reply("form-intention", {"intention": "a wave from driftwood"}, "the wood suggested it."),
        _reply("make-attempt", {"ask": "a driftwood wave form"}, "trying the assembly."),
        _reply("abandon", {}, "the joints would not hold."),
    )
    perception = ScriptedPerception()
    perception.script("an assembled wood form, unpainted.")

    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=perception,
        gate=ScriptedGate(studiolink),
    )
    runtime.host(store, WREN_ID)

    clock.join()
    await clock.wait_until(clock.now() + timedelta(days=2))
    clock.leave()
    await runtime.shutdown()

    entries = store.all_entries()
    assert len(entries) > born_entries
    assert any(e.kind == "self-aware" for e in entries)
    assert any(e.kind == "abandoned" for e in entries)
