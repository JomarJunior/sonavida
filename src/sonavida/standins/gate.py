"""The `AiGate` stand-in (R-9, FR-019, FR-042). The real component is **🧐 CuraGusta**
(roadmap 006).

Pre-alpha default: accepts every submission and keeps the persona's own suggested
labels, clearly logged as a stand-in, never silently. This is the only code that ever
calls `StudioLink.hand_over_candidate` (Principle III) — and it does so only for the
in-process Studio Link reference stand-in (R-9): handed anything else, it refuses.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from miraveja_studiolink.messages.common import PersonaRef
from miraveja_studiolink.messages.common import Verdict as LinkVerdict

from sonavida.ports.gate import Verdict
from sonavida.ports.studiolink import LABEL_TO_LINK, StudioLink

logger = logging.getLogger(__name__)


class GateBypassRefused(Exception):
    """R-9, Principle III: the gate stand-in only ever hands a candidate to the
    in-process Studio Link reference stand-in."""


@dataclass
class ScriptedGate:
    studiolink: StudioLink
    is_reference_standin: bool = True
    _queue: deque[Verdict] = field(default_factory=deque)

    def script(self, *verdicts: Verdict) -> None:
        self._queue.extend(verdicts)

    async def submit(
        self,
        *,
        persona_id: uuid.UUID,
        public_name: str,
        piece_id: uuid.UUID,
        title: str,
        statement: str,
        image_bytes: bytes,
        neutral_description: str,
        suggested_labels: frozenset[str],
    ) -> Verdict:
        if not self.is_reference_standin:
            raise GateBypassRefused(
                "the AI gate stand-in only ever hands a candidate to the in-process "
                "Studio Link reference stand-in (Principle III, R-9)"
            )
        verdict = (
            self._queue.popleft()
            if self._queue
            else Verdict(
                accepted=True,
                reason="pre-alpha stand-in: accepted by default.",
                labels=frozenset(suggested_labels),
            )
        )
        logger.info(
            "AiGate stand-in verdict for piece %s: accepted=%s (stand-in, not a real gate)",
            piece_id,
            verdict.accepted,
        )
        if verdict.accepted:
            persona_ref = PersonaRef(personaId=persona_id, publicName=public_name)
            link_verdict = LinkVerdict(
                outcome="accepted",
                reason=verdict.reason,
                decidedAt=datetime.now(UTC),
                scope="hard_lines_only",
            )
            await self.studiolink.hand_over_candidate(
                persona=persona_ref,
                piece_id=piece_id,
                title=title,
                statement=statement,
                neutral_description=neutral_description,
                labels=[LABEL_TO_LINK[label] for label in verdict.labels],
                verdict=link_verdict,
                image_bytes=image_bytes,
            )
        return verdict
