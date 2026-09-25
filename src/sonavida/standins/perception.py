"""Perception stand-ins (R-9, FR-013). The real component is **💬 DescriDiva** (roadmap 005).

The default stand-in asks `Models` for a neutral description of the image with a
plain, judgment-free instruction; a scripted one answers with fixed descriptions for
tests. The persona sees its own work only through this port.
"""

from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass, field

from sonavida.ports.models import ModelResult, Models

NEUTRAL_INSTRUCTION = (
    "Describe plainly and neutrally what this image shows: subject, composition and "
    "color. No judgment, no style commentary, no guess at intent — only what is "
    "visibly there."
)


@dataclass
class ModelsPerception:
    """Asks `Models` for a description with a fixed, neutral instruction (R-9)."""

    models: Models
    instruction: str = NEUTRAL_INSTRUCTION

    async def describe(self, image_bytes: bytes) -> str:
        outcome = await self.models.text(
            self.instruction,
            images=({"mediaType": "image/png", "base64": base64.b64encode(image_bytes).decode()},),
        )
        if isinstance(outcome, ModelResult) and outcome.text:
            return outcome.text
        return "the image could not be described right now."


@dataclass
class ScriptedPerception:
    """A scripted stand-in for tests: a FIFO of descriptions, then a default."""

    default_description: str = "a plain shape, nothing more."
    _queue: deque[str] = field(default_factory=deque)

    def script(self, *descriptions: str) -> None:
        self._queue.extend(descriptions)

    async def describe(self, image_bytes: bytes) -> str:
        if self._queue:
            return self._queue.popleft()
        return self.default_description
