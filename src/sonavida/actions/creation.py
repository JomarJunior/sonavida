"""Creation: form-intention, make-attempt, look-again, rework, finish, abandon.

FR-010, FR-012, FR-014, FR-016.

Judgment call: the turn protocol's `finish` is valid only "with a kept attempt"
(contracts/turn-protocol.md), and the data model's attempt outcomes name one directly:
`kept-as-final`. Nothing in the closed action set is a separate "keep this attempt"
choice, so a successful attempt starts `kept-as-final` — the persona's current
candidate for the piece — until `rework` supersedes it (`reworked`) or the Studio
could not produce it (`did-not-come-out`, `interrupted`); `finish` uses the referenced
attempt's image without changing its outcome further. This is the one reading that
makes the contract's precondition and the data model's vocabulary agree.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from sonavida.memory.store import Attempt, MemoryStore
from sonavida.ports.models import ModelOutcome, ModelResult, Models, Stopping
from sonavida.ports.perception import Perception


def build_image_description(ask: str, self_knowledge: Mapping[str, object]) -> str:
    """FR-011: the persona's `ask` verbatim, plus only its own craft and stylesAndMedia
    words — never a subject, style or intent of the runtime's own choosing."""
    parts = [ask]
    for key in ("stylesAndMedia", "craft"):
        value = self_knowledge.get(key)
        if value:
            parts.append(str(value))
    return "\n".join(parts)


def form_intention(
    *, store: MemoryStore, intention: str, reason: str, importance: int, at: datetime
) -> str:
    entry_id = store.append(
        at=at, kind="intention", text=intention, reason=reason, importance=importance
    )
    piece_id = str(uuid.uuid4())
    store.create_piece(piece_id=piece_id, intention_entry=entry_id)
    return piece_id


async def make_attempt(
    *,
    store: MemoryStore,
    models: Models,
    self_knowledge: Mapping[str, object],
    piece_dir: Path,
    piece_id: str,
    ask: str,
    reason: str,
    importance: int,
    at: datetime,
) -> tuple[int, ModelOutcome | None]:
    """Returns the attempt id, and the Studio-limit outcome if the attempt did not
    succeed (`None` on success — R-7 is `life.py`'s job to translate)."""
    attempt_id = store.add_attempt(piece_id=piece_id, asked=ask, outcome="kept-as-final")
    description = build_image_description(ask, self_knowledge)
    outcome = await models.image(description)
    if isinstance(outcome, ModelResult) and outcome.image_bytes is not None:
        piece_dir.mkdir(parents=True, exist_ok=True)
        image_path = piece_dir / f"attempt-{attempt_id}.png"
        image_path.write_bytes(outcome.image_bytes)
        store.update_attempt(attempt_id, image_path=str(image_path))
        store.append(
            at=at, kind="attempt", text=ask, reason=reason, importance=importance, piece_id=piece_id
        )
        return attempt_id, None
    outcome_name = "interrupted" if isinstance(outcome, Stopping) else "did-not-come-out"
    store.update_attempt(attempt_id, outcome=outcome_name)
    return attempt_id, outcome


def _attempt(store: MemoryStore, piece_id: str, attempt_id: int) -> Attempt:
    for attempt in store.attempts_for(piece_id):
        if attempt.id == attempt_id:
            return attempt
    raise LookupError(f"no such attempt: {attempt_id} for piece {piece_id}")


async def look_again(
    *,
    store: MemoryStore,
    perception: Perception,
    piece_id: str,
    attempt_id: int,
    reason: str,
    importance: int,
    at: datetime,
) -> str:
    attempt = _attempt(store, piece_id, attempt_id)
    assert attempt.image_path is not None
    image_bytes = Path(attempt.image_path).read_bytes()
    description = await perception.describe(image_bytes)
    store.update_attempt(attempt_id, seen=description)
    store.append(
        at=at,
        kind="attempt-seen",
        text=description,
        reason=reason,
        importance=importance,
        piece_id=piece_id,
    )
    return description


async def rework(
    *,
    store: MemoryStore,
    models: Models,
    self_knowledge: Mapping[str, object],
    piece_dir: Path,
    piece_id: str,
    old_attempt_id: int,
    ask: str,
    reason: str,
    importance: int,
    at: datetime,
) -> tuple[int, ModelOutcome | None]:
    store.update_attempt(old_attempt_id, outcome="reworked")
    return await make_attempt(
        store=store,
        models=models,
        self_knowledge=self_knowledge,
        piece_dir=piece_dir,
        piece_id=piece_id,
        ask=ask,
        reason=reason,
        importance=importance,
        at=at,
    )


def finish(
    *,
    store: MemoryStore,
    piece_id: str,
    attempt_id: int,
    title: str,
    statement: str,
    reason: str,
    importance: int,
    at: datetime,
) -> None:
    attempt = _attempt(store, piece_id, attempt_id)
    store.update_piece(
        piece_id, state="finished", title=title, statement=statement, image_path=attempt.image_path
    )
    store.append(
        at=at, kind="finished", text=title, reason=reason, importance=importance, piece_id=piece_id
    )


def abandon(
    *, store: MemoryStore, piece_id: str, reason: str, importance: int, at: datetime
) -> None:
    store.update_piece(piece_id, state="abandoned")
    store.append(
        at=at,
        kind="abandoned",
        text="abandoned the piece.",
        reason=reason,
        importance=importance,
        piece_id=piece_id,
    )
