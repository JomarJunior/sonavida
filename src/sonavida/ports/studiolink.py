"""The `StudioLink` port: presence, candidates, experiences, erasure (ports.md).

Wraps `miraveja_studiolink.StudioLinkClient`, Studio-initiated only (Principle V). The
same client, pointed at the in-process reference stand-in, is used in tests.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from miraveja_studiolink.client.client import StudioLinkClient
from miraveja_studiolink.messages.candidates import Label
from miraveja_studiolink.messages.common import PersonaRef
from miraveja_studiolink.messages.common import Verdict as LinkVerdict
from miraveja_studiolink.messages.erasure import ErasureNoticeBatch
from miraveja_studiolink.messages.experiences import ExperienceBatch
from miraveja_studiolink.messages.presence import PresenceState

# The persona's own vocabulary is "violent" (data-model.md); the contract's is "violence".
LABEL_TO_LINK: dict[str, Label] = {"explicit": "explicit", "violent": "violence"}
LABEL_FROM_LINK: dict[str, str] = {"explicit": "explicit", "violence": "violent"}


class StudioLink(Protocol):
    async def announce_presence(self, persona: PersonaRef, state: PresenceState) -> None: ...

    async def hand_over_candidate(
        self,
        *,
        persona: PersonaRef,
        piece_id: uuid.UUID,
        title: str,
        statement: str,
        neutral_description: str,
        labels: list[Label],
        verdict: LinkVerdict,
        image_bytes: bytes,
    ) -> None: ...

    async def collect_experiences(
        self, persona_id: uuid.UUID, *, from_sequence: int | None = None
    ) -> ExperienceBatch: ...

    async def acknowledge_experiences(
        self, persona_id: uuid.UUID, through_sequence: int
    ) -> None: ...

    async def collect_erasure_notices(
        self, persona_id: uuid.UUID, *, from_sequence: int | None = None
    ) -> ErasureNoticeBatch: ...

    async def acknowledge_erasure_notices(
        self, persona_id: uuid.UUID, through_sequence: int
    ) -> None: ...


class RealStudioLink:
    """Adapts `StudioLinkClient` to the `StudioLink` port."""

    def __init__(self, client: StudioLinkClient) -> None:
        self._client = client

    async def announce_presence(self, persona: PersonaRef, state: PresenceState) -> None:
        await self._client.announce_presence(persona, state)

    async def hand_over_candidate(
        self,
        *,
        persona: PersonaRef,
        piece_id: uuid.UUID,
        title: str,
        statement: str,
        neutral_description: str,
        labels: list[Label],
        verdict: LinkVerdict,
        image_bytes: bytes,
    ) -> None:
        await self._client.hand_over_candidate(
            send_mark=uuid.uuid4(),
            persona=persona,
            piece_id=piece_id,
            title=title,
            statement=statement,
            neutral_description=neutral_description,
            labels=labels,
            verdict=verdict,
            image_bytes=image_bytes,
        )

    async def collect_experiences(
        self, persona_id: uuid.UUID, *, from_sequence: int | None = None
    ) -> ExperienceBatch:
        return await self._client.collect_experiences(persona_id, from_sequence=from_sequence)

    async def acknowledge_experiences(self, persona_id: uuid.UUID, through_sequence: int) -> None:
        await self._client.acknowledge_experiences(persona_id, through_sequence)

    async def collect_erasure_notices(
        self, persona_id: uuid.UUID, *, from_sequence: int | None = None
    ) -> ErasureNoticeBatch:
        return await self._client.collect_erasure_notices(persona_id, from_sequence=from_sequence)

    async def acknowledge_erasure_notices(
        self, persona_id: uuid.UUID, through_sequence: int
    ) -> None:
        await self._client.acknowledge_erasure_notices(persona_id, through_sequence)
