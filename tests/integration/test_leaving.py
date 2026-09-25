"""T045: leaving takes effect on the second consecutive choice only (FR-040, R-11)."""

from __future__ import annotations

import json
import stat
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sonavida import birth
from sonavida.memory.store import MemoryStore
from sonavida.ports.clock import SimulatedClock
from sonavida.runtime import Departed, Runtime
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.models import ScriptedModels
from sonavida.standins.perception import ScriptedPerception

from ..conftest import PELLAM_ID
from .conftest import StudioLinkAndState


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
    return SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=5)


async def test_one_choice_is_thinking_of_leaving_only(
    tmp_path: Path, examples: Path, clock: SimulatedClock, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    store = birth.birth_synthetic(
        PELLAM_ID, examples / "pellam-quist.persona.yaml", home=home, clock=clock
    )
    models = ScriptedModels()
    models.script_text(_reply("leave-the-museum", {}, "the studio feels too quiet lately."))

    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    life = runtime.host(store, PELLAM_ID)
    clock.join()
    await clock.wait_until(clock.now() + timedelta(hours=2))
    clock.leave()
    await runtime.shutdown()

    kinds = [e.kind for e in store.all_entries()]
    assert "thinking-of-leaving" in kinds
    assert "departed" not in kinds
    assert not life.departed


async def test_a_non_consecutive_second_choice_does_not_count(
    tmp_path: Path, examples: Path, clock: SimulatedClock, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    store = birth.birth_synthetic(
        PELLAM_ID, examples / "pellam-quist.persona.yaml", home=home, clock=clock
    )
    models = ScriptedModels()
    models.script_text(
        _reply("leave-the-museum", {}, "thinking about it."),
        _reply("do-nothing", {}, "changed my mind, resting instead."),
        _reply("leave-the-museum", {}, "thinking about it again."),
    )

    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    life = runtime.host(store, PELLAM_ID)
    clock.join()
    await clock.wait_until(clock.now() + timedelta(hours=4))
    clock.leave()
    await runtime.shutdown()

    kinds = [e.kind for e in store.all_entries()]
    assert kinds.count("thinking-of-leaving") == 2
    assert "departed" not in kinds
    assert not life.departed


async def test_two_consecutive_choices_complete_the_departure(
    tmp_path: Path, examples: Path, clock: SimulatedClock, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    home = tmp_path / "home"
    store = birth.birth_synthetic(
        PELLAM_ID, examples / "pellam-quist.persona.yaml", home=home, clock=clock
    )
    models = ScriptedModels()
    models.script_text(
        _reply("leave-the-museum", {}, "I've thought about it enough."),
        _reply("leave-the-museum", {}, "yes, it's time."),
    )

    runtime = Runtime(
        home=home,
        clock=clock,
        models=models,
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    life = runtime.host(store, PELLAM_ID)
    clock.join()
    await clock.wait_until(clock.now() + timedelta(hours=4))
    clock.leave()
    await runtime.shutdown()

    assert life.departed
    reopened = MemoryStore(store.path, mode="ro")
    kinds = [e.kind for e in reopened.all_entries()]
    assert kinds.count("thinking-of-leaving") == 1
    assert kinds.count("departed") == 1
    # announced away exactly once (the departure itself, not a second shutdown
    # announcement — runtime.py skips that once a persona has already departed).
    presence_announcements = [
        e for e in reopened.all_entries() if e.kind == "presence" and e.text == "away"
    ]
    assert len(presence_announcements) == 0  # departure uses the Studio Link directly,
    # not a `presence` memory entry of its own (data-model.md: `departed` is the record).

    memory_path = store.path
    mode = memory_path.stat().st_mode
    assert not (mode & stat.S_IWUSR), "memory must be read-only on disk after departure"

    lock_path = home / "personas" / PELLAM_ID / "lock"
    assert lock_path.exists()
    # the lock is released: a fresh runtime can take it without a conflict.
    from sonavida.runtime import PersonaLock

    fresh_lock = PersonaLock(home, PELLAM_ID)
    fresh_lock.release()

    record = state.personas.get(uuid.UUID(PELLAM_ID))
    assert record is not None
    assert record.presence_state == "away"


async def test_run_refuses_a_departed_persona(
    tmp_path: Path, examples: Path, clock: SimulatedClock, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    store = birth.birth_synthetic(
        PELLAM_ID, examples / "pellam-quist.persona.yaml", home=home, clock=clock
    )
    models = ScriptedModels()
    models.script_text(
        _reply("leave-the-museum", {}, "enough thought."),
        _reply("leave-the-museum", {}, "time to go."),
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
    await clock.wait_until(clock.now() + timedelta(hours=4))
    clock.leave()
    await runtime.shutdown()

    reopened = birth.birth_synthetic(
        PELLAM_ID, examples / "pellam-quist.persona.yaml", home=home, clock=clock
    )
    second_runtime = Runtime(
        home=home,
        clock=clock,
        models=ScriptedModels(),
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    with pytest.raises(Departed):
        second_runtime.host(reopened, PELLAM_ID)
