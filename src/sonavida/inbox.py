"""Collecting from the Studio Link: experiences and erasure notices (R-8, FR-022 to FR-024).

Each is acknowledged only once it is safely stored or acted on. Collecting happens on
every turn regardless of presence — it is the Studio's own work, not an interruption
of the persona's rest (spec Edge Cases).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from miraveja_studiolink.messages.experiences import Experience
from miraveja_studiolink.messages.refusal import RefusalReceived

from sonavida.memory.erasure import erase_visitor
from sonavida.memory.store import MemoryStore
from sonavida.memory.tokens import token_for
from sonavida.ports.studiolink import StudioLink

logger = logging.getLogger(__name__)

_GATE_OUTCOME_TO_PIECE_STATE = {
    "exhibited": "exhibited",
    "declined": "declined",
    "taken_down": "taken-down",
}

# A refusal on its own is unremarkable (a persona not yet announced, a momentary
# hiccup); this many turns in a row is not, and the team should be told once, at
# error level, with the reason code only — never the batch content (Principle VIII).
CONSECUTIVE_REFUSAL_ALERT_THRESHOLD = 3


def _note_refusal(counts: dict[str, int], queue: str, persona_id: uuid.UUID, reason: str) -> None:
    count = counts.get(queue, 0) + 1
    counts[queue] = count
    logger.warning("%s refused for %s: %s", queue, persona_id, reason)
    if count == CONSECUTIVE_REFUSAL_ALERT_THRESHOLD:
        logger.error(
            "%s for %s refused %d turns in a row (%s); the queue may be stuck",
            queue,
            persona_id,
            count,
            reason,
        )


def _note_success(counts: dict[str, int], queue: str) -> None:
    counts[queue] = 0


def _store_experience(store: MemoryStore, item: Experience, at: datetime) -> None:
    kind = item.kind
    sequence = item.sequence
    if kind == "comment":
        author = item.author
        piece_id = str(item.onPieceId) if item.onPieceId else None
        if hasattr(author, "pseudonym"):
            token = token_for(author.pseudonym)
            store.append(
                at=at,
                kind="experience",
                text=f"{token} commented: {item.text}",
                importance=2,
                piece_id=piece_id,
                visitor_pseudonym=author.pseudonym,
                visitor_name=author.displayName,
                source_sequence=sequence,
            )
        else:
            store.append(
                at=at,
                kind="experience",
                text=f"another artist commented: {item.text}",
                importance=2,
                piece_id=piece_id,
                source_sequence=sequence,
            )
    elif kind == "reaction":
        visitor = item.visitor
        token = token_for(visitor.pseudonym)
        store.append(
            at=at,
            kind="experience",
            text=f"{token} reacted with {item.reaction}.",
            importance=2,
            piece_id=str(item.onPieceId),
            visitor_pseudonym=visitor.pseudonym,
            visitor_name=visitor.displayName,
            source_sequence=sequence,
        )
    elif kind == "gate_outcome":
        piece_id = str(item.pieceId)
        outcome = item.outcome
        try:
            store.update_piece(piece_id, state=_GATE_OUTCOME_TO_PIECE_STATE[outcome])
        except LookupError:
            # Edge case: an experience for a piece this persona does not remember
            # submitting. Remembered as it arrived; the mismatch is the team's to see
            # in the logs, never a technical explanation given to the persona.
            logger.warning("gate outcome for unknown piece %s", piece_id)
        text = item.reason or f"the piece was {outcome.replace('_', ' ')}."
        store.append(
            at=at,
            kind="experience",
            text=text,
            importance=2,
            piece_id=piece_id,
            source_sequence=sequence,
        )


async def collect_experiences(
    store: MemoryStore,
    studiolink: StudioLink,
    persona_id: uuid.UUID,
    at: datetime,
    *,
    refusal_counts: dict[str, int] | None = None,
) -> int:
    counts = refusal_counts if refusal_counts is not None else {}
    from_sequence = store.experiences_acknowledged_through() + 1
    try:
        batch = await studiolink.collect_experiences(persona_id, from_sequence=from_sequence)
    except RefusalReceived as refusal:
        # A message the Studio end itself refused (spec 001 FR-023, an unknown field
        # or the like) — or a persona not yet known to the Museum side because it has
        # never announced its presence. Either way nothing reaches the persona and
        # nothing is stored (FR-028); it is simply collected again next turn.
        _note_refusal(counts, "experiences", persona_id, refusal.reason)
        return 0
    _note_success(counts, "experiences")
    for item in batch.items:
        _store_experience(store, item, at)
        store.set_experiences_acknowledged_through(item.sequence)
        await studiolink.acknowledge_experiences(persona_id, item.sequence)
    return len(batch.items)


async def collect_erasure_notices(
    store: MemoryStore,
    studiolink: StudioLink,
    persona_id: uuid.UUID,
    *,
    refusal_counts: dict[str, int] | None = None,
) -> int:
    counts = refusal_counts if refusal_counts is not None else {}
    from_sequence = store.erasures_acknowledged_through() + 1
    try:
        batch = await studiolink.collect_erasure_notices(persona_id, from_sequence=from_sequence)
    except RefusalReceived as refusal:
        _note_refusal(counts, "erasure-notices", persona_id, refusal.reason)
        return 0
    _note_success(counts, "erasure-notices")
    for notice in batch.items:
        erase_visitor(store, notice.pseudonym)
        store.set_erasures_acknowledged_through(notice.sequence)
        await studiolink.acknowledge_erasure_notices(persona_id, notice.sequence)
    return len(batch.items)
