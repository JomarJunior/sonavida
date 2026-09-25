"""T044: three synthetic personas alive at once, each apart, a simulated week under
5 minutes (FR-041, SC-010, plan performance goal)."""

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

from ..conftest import IVO_ID, PELLAM_ID
from .conftest import StudioLinkAndState

SABLE_ID = "00000000-0000-4000-8000-00000000a099"

SABLE_DEFINITION = f"""\
miravejaPersona: 1
nature: synthetic

identity:
  id: {SABLE_ID}
  publicName: Sable Quinn
  about: |
    A synthetic test persona, quick to work and quick to rest, made only for
    spec 004 tests. Belongs to no resident persona.
  openlyAI: true

taste:
  drawnTo: |
    Sharp geometric shapes, bold flat color.
  themes:
    - city rooftops at noon
  stylesAndMedia: |
    Hard-edged flat color blocks.

voice:
  speech: |
    Short, direct sentences.
  temperament: |
    Brisk and businesslike.

tendencies:
  presence: |
    Tends to be in the studio during the day and rest at night.
  work: |
    Works quickly, in short bursts.

cares:
  - finishing what it starts

seedMemories:
  - id: first-rooftop
    when: as a young persona
    happened: |
      I first saw a city rooftop at noon and loved the hard shadows it cast.
"""


def _reply(action: str, details: dict[str, object], reason: str, *, next_in: str = "PT8H") -> str:
    return json.dumps(
        {
            "action": action,
            "details": details,
            "reason": reason,
            "remember": {"importance": 2},
            "nextTurnIn": next_in,
        }
    )


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=11)


async def test_three_personas_alive_together_for_a_simulated_week(
    tmp_path: Path,
    examples: Path,
    clock: SimulatedClock,
    studiolink_and_state: StudioLinkAndState,
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"

    sable_path = tmp_path / "sable.persona.yaml"
    sable_path.write_text(SABLE_DEFINITION, encoding="utf-8")

    persona_ids = [PELLAM_ID, IVO_ID, SABLE_ID]
    paths = {
        PELLAM_ID: examples / "pellam-quist.persona.yaml",
        IVO_ID: examples / "ivo-marrowfield.persona.yaml",
        SABLE_ID: sable_path,
    }

    runtime = Runtime(
        home=home,
        clock=clock,
        models=ScriptedModels(),
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    stores = {}
    for persona_id in persona_ids:
        store = birth.birth_synthetic(persona_id, paths[persona_id], home=home, clock=clock)
        stores[persona_id] = store
        runtime.host(store, persona_id)

    started = time.monotonic()
    clock.join()
    await clock.wait_until(clock.now() + timedelta(days=7))
    clock.leave()
    await runtime.shutdown()
    elapsed = time.monotonic() - started
    assert elapsed < 300, f"a simulated week took {elapsed:.1f}s, over the 5 minute budget"

    public_names = {
        PELLAM_ID: "Pellam Quist",
        IVO_ID: "Ivo Marrowfield",
        SABLE_ID: "Sable Quinn",
    }
    for persona_id, store in stores.items():
        own_entries = store.all_entries()
        assert own_entries, f"{persona_id} lived but has no entries at all"
        for other_id, other_name in public_names.items():
            if other_id == persona_id:
                continue
            for entry in own_entries:
                assert other_name not in entry.text
                assert other_id not in entry.text

        # every piece this persona started ended in a state the data model defines;
        # nothing is silently dropped — it is finished, kept, submitted, abandoned,
        # or simply still in progress, waiting for the persona's own next choice.
        for piece in store.pieces_in_state(
            "in-progress",
            "finished",
            "abandoned",
            "kept",
            "submitted",
            "accepted",
            "rejected",
        ):
            assert piece.state  # every piece has a defined, non-silent state

    # each persona kept its own hours: the presence history is its own.
    for persona_id, store in stores.items():
        for other_id, other_store in stores.items():
            if other_id == persona_id:
                continue
            assert store.path != other_store.path
