"""T018: replies are validated against the turn-protocol schema; one retry, then lost-thread."""

from __future__ import annotations

import json

import pytest

from sonavida.ports.models import Busy
from sonavida.standins.models import ScriptedModels
from sonavida.turns.reply import LostThread, TurnReply, ValidationError, get_reply, parse_reply

VALID_ACTIONS = frozenset({"set-presence", "do-nothing", "leave-the-museum"})


def _reply(action: str = "do-nothing", **overrides: object) -> str:
    payload: dict[str, object] = {
        "action": action,
        "details": {},
        "reason": "nothing calls to me today.",
        "remember": {"importance": 2},
        "nextTurnIn": "PT2H",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_a_well_formed_reply_parses() -> None:
    reply = parse_reply(_reply(), valid_actions=VALID_ACTIONS)
    assert isinstance(reply, TurnReply)
    assert reply.action == "do-nothing"
    assert reply.importance == 2
    from datetime import timedelta

    assert reply.next_turn_in == timedelta(hours=2)


def test_action_must_be_valid_in_the_state() -> None:
    with pytest.raises(ValidationError):
        parse_reply(_reply(action="form-intention"), valid_actions=VALID_ACTIONS)


def test_details_must_be_exactly_what_the_action_needs() -> None:
    with pytest.raises(ValidationError):
        parse_reply(_reply(action="set-presence", details={}), valid_actions=VALID_ACTIONS)
    with pytest.raises(ValidationError):
        parse_reply(
            _reply(action="do-nothing", details={"extra": "field"}),
            valid_actions=VALID_ACTIONS,
        )


def test_reason_is_required() -> None:
    with pytest.raises(ValidationError):
        parse_reply(_reply(reason=""), valid_actions=VALID_ACTIONS)


@pytest.mark.parametrize("importance", [0, 6, "high", None])
def test_importance_must_be_1_to_5(importance: object) -> None:
    with pytest.raises(ValidationError):
        parse_reply(_reply(remember={"importance": importance}), valid_actions=VALID_ACTIONS)


def test_next_turn_in_must_be_an_iso_duration() -> None:
    with pytest.raises(ValidationError):
        parse_reply(_reply(nextTurnIn="in two hours"), valid_actions=VALID_ACTIONS)


async def test_one_retry_with_the_validation_message() -> None:
    models = ScriptedModels()
    models.script_text("not json at all", _reply())
    outcome = await get_reply(models, "prompt", valid_actions=VALID_ACTIONS)
    assert isinstance(outcome, TurnReply)
    assert len(models.calls) == 2
    assert "could not be read" in models.calls[1][1]


async def test_a_second_failure_becomes_lost_thread() -> None:
    models = ScriptedModels()
    models.script_text("still not json", "also not json")
    outcome = await get_reply(models, "prompt", valid_actions=VALID_ACTIONS)
    assert isinstance(outcome, LostThread)
    assert len(models.calls) == 2


async def test_a_good_first_reply_needs_no_retry() -> None:
    models = ScriptedModels()
    models.script_text(_reply())
    outcome = await get_reply(models, "prompt", valid_actions=VALID_ACTIONS)
    assert isinstance(outcome, TurnReply)
    assert len(models.calls) == 1


async def test_the_studio_being_busy_is_returned_unchanged() -> None:
    models = ScriptedModels()
    models.script(Busy())
    outcome = await get_reply(models, "prompt", valid_actions=VALID_ACTIONS)
    assert isinstance(outcome, Busy)
