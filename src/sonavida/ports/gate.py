"""The `AiGate` port (FR-018 to FR-021, FR-042, R-9).

Real implementation: **🧐 CuraGusta** (roadmap 006), a seam left for that spec.
Until then, `standins/gate.py` (T031) provides it, and is the only code allowed to
call `StudioLink.hand_over_candidate` (Principle III).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str
    labels: frozenset[str]
    feedback: str | None = None


class AiGate(Protocol):
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
    ) -> Verdict: ...
