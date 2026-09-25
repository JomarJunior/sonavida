"""T034: with twenty reactions on one piece, nothing SonaVida produces — prompt or
memory entry — carries a count, total, average, rank, rating, trend, comparison or
money (FR-027, SC-005)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida import inbox
from sonavida.memory.store import MemoryStore
from sonavida.turns.prompt import build_prompt
from sonavida.turns.proposals import build_proposals
from sonavida.turns.state import TurnState

from ..conftest import StudioLinkAndState

PERSONA_ID = uuid.UUID("00000000-0000-4000-8000-00000000a001")
PIECE_ID = uuid.uuid4()

# Constructs that would betray a metric leaking into what the persona is given.
METRIC_WORDS = (
    "total",
    "average",
    "mean",
    "rank",
    "ranking",
    "rating",
    "score",
    "trend",
    "percent",
    "%",
    "compare",
    "comparison",
    "$",
    "dollar",
    "usd",
    "revenue",
    "top",
    "most popular",
    "best",
)
# A bare integer standing alone, not as part of a date/time, would be a count.
_BARE_NUMBER_RE = re.compile(r"(?<![\w:/-])\d+(?![\w:/-])")


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _assert_no_metrics(text: str) -> None:
    lowered = text.lower()
    for word in METRIC_WORDS:
        assert word not in lowered, f"found a metric word {word!r} in: {text!r}"


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    s = MemoryStore(tmp_path / "memory.sqlite")
    s.write_self(
        persona_id=str(PERSONA_ID), public_name="Pellam Quist", self_knowledge={}, born_at=_now()
    )
    return s


async def test_twenty_reactions_leave_no_metric_in_memory(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await state.seed_exhibited_piece(
        piece_id=PIECE_ID,
        persona_id=PERSONA_ID,
        public_name="Pellam Quist",
        title="Harbor",
        statement="A quiet harbor.",
        neutral_description="a harbor scene.",
    )
    reactions = ["love", "like", "laugh", "wonder", "sorrow"]
    for i in range(20):
        visitor_id = f"visitor-{i}"
        state.add_visitor(visitor_id, f"Visitor {i}")
        await state.script_reaction(
            piece_id=PIECE_ID, visitor_id=visitor_id, reaction=reactions[i % len(reactions)]
        )

    collected = await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())
    assert collected == 20

    entries = [e for e in store.all_entries() if e.kind == "experience"]
    assert len(entries) == 20
    for entry in entries:
        _assert_no_metrics(entry.text)
        # each reaction is an individual sentence naming one reaction, never a count.
        assert entry.text.count("reacted with") == 1


async def test_the_prompt_never_aggregates_recalled_experiences(
    store: MemoryStore, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, state = studiolink_and_state
    await state.seed_exhibited_piece(
        piece_id=PIECE_ID,
        persona_id=PERSONA_ID,
        public_name="Pellam Quist",
        title="Harbor",
        statement="A quiet harbor.",
        neutral_description="a harbor scene.",
    )
    for i in range(20):
        visitor_id = f"visitor-{chr(ord('a') + i)}"
        state.add_visitor(visitor_id, f"Visitor {chr(ord('A') + i)}")
        await state.script_reaction(piece_id=PIECE_ID, visitor_id=visitor_id, reaction="love")
    await inbox.collect_experiences(store, studiolink, PERSONA_ID, _now())

    recalled = store.recall("reacted", budget=20)
    prompt = build_prompt(
        self_knowledge={},
        now=_now(),
        presence="in-the-studio",
        last_turn_at=None,
        working_on=None,
        recalled=recalled,
        proposals=build_proposals(TurnState(presence="in-the-studio"), {}),
    )
    _assert_no_metrics(prompt.text)
    # twenty individual mentions of the reaction are fine; a computed figure is not.
    assert prompt.text.count("reacted with love") == len(recalled)
    for line in prompt.text.splitlines():
        if "reacted with" in line:
            numbers = _BARE_NUMBER_RE.findall(line)
            assert not numbers, f"a bare number in a recalled line: {line!r}"
