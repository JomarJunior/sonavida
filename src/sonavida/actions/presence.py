"""`set-presence`: announced through the Studio Link and remembered with its reason (FR-007)."""

from __future__ import annotations

from datetime import datetime

from miraveja_studiolink.messages.common import PersonaRef
from miraveja_studiolink.messages.presence import PresenceState

from sonavida.memory.store import MemoryStore
from sonavida.ports.studiolink import StudioLink
from sonavida.turns.state import Presence

_TO_LINK: dict[Presence, PresenceState] = {
    "in-the-studio": "in_the_studio",
    "resting": "resting",
    "away": "away",
}


async def set_presence(
    *,
    store: MemoryStore,
    studiolink: StudioLink,
    persona: PersonaRef,
    state: Presence,
    reason: str,
    importance: int,
    at: datetime,
) -> None:
    store.append(at=at, kind="presence", text=state, reason=reason, importance=importance)
    await studiolink.announce_presence(persona, _TO_LINK[state])
