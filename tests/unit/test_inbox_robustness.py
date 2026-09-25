"""Inbox robustness: several consecutive refusals are logged once at error level, by
reason code only; the persona's own life is unaffected (never raises, never stalls)."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from miraveja_studiolink.messages.erasure import ErasureNoticeBatch
from miraveja_studiolink.messages.experiences import ExperienceBatch
from miraveja_studiolink.messages.refusal import RefusalReceived

from sonavida import inbox
from sonavida.memory.store import MemoryStore

PERSONA_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    s = MemoryStore(tmp_path / "memory.sqlite")
    s.write_self(
        persona_id=str(PERSONA_ID), public_name="Pellam Quist", self_knowledge={}, born_at=_now()
    )
    return s


class _AlwaysRefusingStudioLink:
    """Shaped like the `StudioLink` port; every collect call is refused."""

    async def collect_experiences(
        self, persona_id: uuid.UUID, *, from_sequence: int | None = None
    ) -> ExperienceBatch:
        raise RefusalReceived("malformed", detail="never printed")

    async def collect_erasure_notices(
        self, persona_id: uuid.UUID, *, from_sequence: int | None = None
    ) -> ErasureNoticeBatch:
        raise RefusalReceived("malformed", detail="never printed")


class _RecoveringStudioLink(_AlwaysRefusingStudioLink):
    """Refused twice, then answers with nothing waiting."""

    def __init__(self) -> None:
        self.calls = 0

    async def collect_experiences(
        self, persona_id: uuid.UUID, *, from_sequence: int | None = None
    ) -> ExperienceBatch:
        self.calls += 1
        if self.calls <= 2:
            raise RefusalReceived("malformed")
        return ExperienceBatch(items=[], nextSequence=None)


async def test_a_refused_queue_never_raises_and_returns_nothing_collected(
    store: MemoryStore,
) -> None:
    studiolink = _AlwaysRefusingStudioLink()
    collected = await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())  # type: ignore[arg-type]
    assert collected == 0
    collected = await inbox.collect_erasure_notices(store, studiolink, PERSONA_ID)  # type: ignore[arg-type]
    assert collected == 0


async def test_error_is_logged_once_after_the_threshold_and_never_carries_content(
    store: MemoryStore, caplog: pytest.LogCaptureFixture
) -> None:
    studiolink = _AlwaysRefusingStudioLink()
    counts: dict[str, int] = {}
    with caplog.at_level(logging.WARNING, logger="sonavida.inbox"):
        for _ in range(5):
            await inbox.collect_experiences(
                store,
                studiolink,  # type: ignore[arg-type]
                PERSONA_ID,
                _now(),
                refusal_counts=counts,
            )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "malformed" in message  # the reason code, and nothing else from the refusal
    assert "never printed" not in message  # the refusal's own `detail` never appears


async def test_the_count_resets_once_the_queue_recovers(store: MemoryStore) -> None:
    studiolink = _RecoveringStudioLink()
    counts: dict[str, int] = {}
    for _ in range(3):
        await inbox.collect_experiences(
            store,
            studiolink,  # type: ignore[arg-type]
            PERSONA_ID,
            _now(),
            refusal_counts=counts,
        )
    assert counts["experiences"] == 0
