"""T013: every Models outcome maps to its situation, with no technical terms (FR-031)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sonavida.ports.models import Busy, CannotServe, Failed, Starting, Stopping
from sonavida.translate import translate

# What must never appear in a translated situation (FR-031, SC-007).
FORBIDDEN_WORDS = (
    "model",
    "queue",
    "modelmora",
    "busy",
    "starting",
    "stopping",
    "failed_during_generation",
    "cannot_be_served_on_this_studio",
    "unknown_model",
    "model_unavailable",
    "invalid_request",
)


@pytest.mark.parametrize(
    "outcome",
    [
        Busy(),
        Busy(retry_at=datetime.now(UTC) + timedelta(hours=1)),
        Starting(),
        Starting(retry_at=datetime.now(UTC) + timedelta(minutes=30)),
        Stopping(),
        Failed(),
        CannotServe(),
    ],
)
def test_every_outcome_maps_to_a_situation(outcome: object) -> None:
    translated = translate(outcome)  # type: ignore[arg-type]
    assert translated.situation
    assert translated.kind


@pytest.mark.parametrize(
    "outcome",
    [
        Busy(retry_at=datetime.now(UTC) + timedelta(hours=2)),
        Starting(retry_at=datetime.now(UTC) + timedelta(minutes=5)),
        Stopping(),
        Failed(),
        CannotServe(),
    ],
)
def test_no_technical_terms_in_any_situation(outcome: object) -> None:
    situation = translate(outcome).situation.lower()  # type: ignore[arg-type]
    for word in FORBIDDEN_WORDS:
        assert word not in situation


def test_no_digit_only_queue_position() -> None:
    situation = translate(Busy(retry_at=datetime.now(UTC) + timedelta(hours=1))).situation
    # a time of day (HH:MM) is allowed; a bare digit token standing for a queue
    # position on its own, such as "position 3", is not.
    assert "position" not in situation
    assert not any(token.isdigit() for token in situation.split())


def test_stopping_is_the_work_was_interrupted() -> None:
    assert translate(Stopping()).situation == "the work was interrupted"
    assert translate(Stopping()).kind == "interrupted"


def test_failed_is_the_attempt_did_not_come_out() -> None:
    assert translate(Failed()).situation == "the attempt did not come out"
    assert translate(CannotServe()).situation == "the attempt did not come out"
