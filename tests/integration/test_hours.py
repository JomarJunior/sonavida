"""T022: a simulated run of a synthetic persona against the Studio Link reference stand-in."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sonavida import birth
from sonavida.ports.clock import SimulatedClock
from sonavida.runtime import AlreadyAlive, Departed, Runtime
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.models import ScriptedModels
from sonavida.standins.perception import ScriptedPerception

from ..conftest import PELLAM_ID
from .conftest import StudioLinkAndState


def _presence_reply(state: str, reason: str, *, next_in: str = "PT6H") -> str:
    return json.dumps(
        {
            "action": "set-presence",
            "details": {"presence": state},
            "reason": reason,
            "remember": {"importance": 2},
            "nextTurnIn": next_in,
        }
    )


@pytest.fixture
def clock() -> SimulatedClock:
    return SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=1)


async def test_one_birth_and_every_chosen_presence_change_is_announced_and_remembered(
    tmp_path: Path,
    examples: Path,
    clock: SimulatedClock,
    studiolink_and_state: StudioLinkAndState,
) -> None:
    studiolink, state = studiolink_and_state
    home = tmp_path / "home"
    path = examples / "pellam-quist.persona.yaml"
    store = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)
    born_entries = len(store.all_entries())

    models = ScriptedModels()
    models.script_text(
        _presence_reply("in-the-studio", "the evening light called me in."),
        _presence_reply("resting", "I have done enough for tonight."),
        _presence_reply("in-the-studio", "back again."),
    )

    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    runtime.host(store, PELLAM_ID)

    clock.join()
    await clock.wait_until(clock.now() + timedelta(days=3))
    clock.leave()
    await runtime.shutdown()

    entries = store.all_entries()
    assert len(entries) > born_entries
    presence_entries = [e for e in entries if e.kind == "presence"]
    assert len(presence_entries) >= 3
    assert all(e.reason for e in presence_entries)

    persona_uuid = uuid.UUID(PELLAM_ID)
    record = state.personas[persona_uuid]
    # the final presence announcement is the shutdown's own "away" (FR-008).
    assert record.presence_state == "away"


async def test_second_start_is_refused_as_already_alive(
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
    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    runtime.host(store, PELLAM_ID)

    store2 = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)
    with pytest.raises(AlreadyAlive):
        runtime.host(store2, PELLAM_ID)

    await runtime.shutdown()


async def test_time_away_is_remembered_after_a_simulated_studio_outage(
    tmp_path: Path, examples: Path, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    path = examples / "pellam-quist.persona.yaml"

    first_clock = SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=1)
    store = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=first_clock)
    store.close()

    later_clock = SimulatedClock(start=datetime(2026, 1, 5, tzinfo=UTC), seed=1)
    from sonavida.memory.store import MemoryStore

    reopened = MemoryStore(birth.persona_memory_path(home, PELLAM_ID))
    models = ScriptedModels()
    runtime = Runtime(
        home=home,
        clock=later_clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    runtime.host(reopened, PELLAM_ID)

    later_clock.join()
    await later_clock.wait_until(later_clock.now() + timedelta(minutes=1))
    later_clock.leave()
    await runtime.shutdown()

    kinds = [e.kind for e in reopened.all_entries()]
    assert "time-away" in kinds


async def test_a_departed_persona_refuses_to_start_again(
    tmp_path: Path,
    examples: Path,
    clock: SimulatedClock,
    studiolink_and_state: StudioLinkAndState,
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    path = examples / "pellam-quist.persona.yaml"
    store = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)
    store.record_departure(clock.now())
    store.close()

    from sonavida.memory.store import MemoryStore

    reopened = MemoryStore(birth.persona_memory_path(home, PELLAM_ID))
    models = ScriptedModels()
    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    with pytest.raises(Departed):
        runtime.host(reopened, PELLAM_ID)
