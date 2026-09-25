"""Validating and, once, retrying a turn's reply (R-10, contracts/turn-protocol.md).

`get_reply` asks the model, validates the JSON reply against the state's valid actions,
retries once with the validation message on failure, and gives up as `LostThread` on a
second failure. If the model itself could not be reached for the turn's thinking (the
Studio is busy, starting or stopping), the raw `Models` outcome is returned unchanged so
`life.py` can translate it the same way as any other Studio limit (R-7).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta

from sonavida.ports.models import Busy, CannotServe, Failed, ModelResult, Models, Starting, Stopping

ACTION_DETAILS: dict[str, frozenset[str]] = {
    "set-presence": frozenset({"presence"}),
    "form-intention": frozenset({"intention"}),
    "make-attempt": frozenset({"ask"}),
    "look-again": frozenset({"attempt"}),
    "rework": frozenset({"attempt", "ask"}),
    "finish": frozenset({"attempt", "title", "statement"}),
    "abandon": frozenset(),
    "submit": frozenset({"piece"}),
    "keep": frozenset({"piece"}),
    "continue-unfinished": frozenset({"piece"}),
    "do-nothing": frozenset(),
    "leave-the-museum": frozenset(),
}
OPTIONAL_DETAILS: dict[str, frozenset[str]] = {"submit": frozenset({"suggestedLabels"})}

LOST_THREAD_REST = timedelta(hours=1)

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)


class ValidationError(Exception):
    pass


@dataclass(frozen=True)
class TurnReply:
    action: str
    details: dict[str, object]
    reason: str
    importance: int
    next_turn_in: timedelta


@dataclass(frozen=True)
class LostThread:
    rest_for: timedelta = LOST_THREAD_REST


ReplyOutcome = TurnReply | LostThread | Busy | Starting | Stopping | Failed | CannotServe


def _parse_duration(value: str) -> timedelta:
    match = _DURATION_RE.match(value)
    if not match or not any(match.groups()):
        raise ValidationError(f"nextTurnIn is not a valid ISO 8601 duration: {value!r}")
    parts = {k: int(v) for k, v in match.groupdict().items() if v}
    return timedelta(
        days=parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
        seconds=parts.get("seconds", 0),
    )


def parse_reply(text: str, *, valid_actions: frozenset[str]) -> TurnReply:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValidationError(f"not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise ValidationError("the reply must be one JSON object")

    action = data.get("action")
    if action not in valid_actions:
        raise ValidationError(f"{action!r} is not an action valid right now")

    details = data.get("details", {})
    if not isinstance(details, dict):
        raise ValidationError("details must be an object")
    required = ACTION_DETAILS.get(action, frozenset())
    allowed = required | OPTIONAL_DETAILS.get(action, frozenset())
    missing = required - details.keys()
    extra = details.keys() - allowed
    if missing:
        raise ValidationError(f"missing details for {action}: {sorted(missing)}")
    if extra:
        raise ValidationError(f"unexpected details for {action}: {sorted(extra)}")
    if action == "submit" and "suggestedLabels" in details:
        labels = details["suggestedLabels"]
        valid_values = ("explicit", "violent")
        if not isinstance(labels, list) or any(label not in valid_values for label in labels):
            raise ValidationError("suggestedLabels must be a list of 'explicit' or 'violent'")

    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("reason is required, in your own words")

    remember = data.get("remember")
    importance = remember.get("importance") if isinstance(remember, dict) else None
    if not isinstance(importance, int) or isinstance(importance, bool) or not 1 <= importance <= 5:
        raise ValidationError("remember.importance is required, 1-5")

    next_turn_raw = data.get("nextTurnIn")
    if not isinstance(next_turn_raw, str):
        raise ValidationError("nextTurnIn is required, an ISO 8601 duration")
    next_turn_in = _parse_duration(next_turn_raw)

    return TurnReply(
        action=action,
        details=details,
        reason=reason,
        importance=importance,
        next_turn_in=next_turn_in,
    )


async def _ask(models: Models, prompt_text: str) -> str | ReplyOutcome:
    outcome = await models.text(prompt_text)
    if isinstance(outcome, ModelResult):
        return outcome.text or ""
    return outcome


async def get_reply(
    models: Models, prompt_text: str, *, valid_actions: frozenset[str]
) -> ReplyOutcome:
    first = await _ask(models, prompt_text)
    if not isinstance(first, str):
        return first
    try:
        return parse_reply(first, valid_actions=valid_actions)
    except ValidationError as first_error:
        retry_prompt = (
            f"{prompt_text}\n\nYour last answer could not be read: {first_error}. "
            "Answer again, with exactly the JSON object described above.\n"
        )
        second = await _ask(models, retry_prompt)
        if not isinstance(second, str):
            return second
        try:
            return parse_reply(second, valid_actions=valid_actions)
        except ValidationError:
            return LostThread()
