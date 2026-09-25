"""`leave-the-museum`: takes effect on the second consecutive choice (R-11, FR-040).

The confirmation guards against a single garbled model reply ending a persona's life
for good, not against its intent (Complexity Tracking, plan.md): the first choice is
remembered as its own thought, and the persona keeps the choice either way.
"""

from __future__ import annotations

from datetime import datetime

from miraveja_studiolink.messages.common import PersonaRef

from sonavida.memory.store import MemoryStore
from sonavida.ports.studiolink import StudioLink


async def choose_to_leave(
    *,
    store: MemoryStore,
    studiolink: StudioLink,
    persona: PersonaRef,
    leaving_pending: bool,
    reason: str,
    importance: int,
    at: datetime,
) -> bool:
    """Records the choice; returns `True` once the departure itself is complete."""
    if not leaving_pending:
        store.append(
            at=at,
            kind="thinking-of-leaving",
            text="thinking of leaving the museum.",
            reason=reason,
            importance=importance,
        )
        return False
    store.append(
        at=at,
        kind="departed",
        text="departed the museum.",
        reason=reason,
        importance=importance,
    )
    store.record_departure(at)
    await studiolink.announce_presence(persona, "away")
    return True
