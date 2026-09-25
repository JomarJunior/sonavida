"""A scripted `Models` stand-in for tests (FR-038).

Returns deterministic text and tiny PNGs by default, and can be scripted to answer
*starting*, *busy*, *stopping* or *failed* for a chosen number of calls, so User Story 6
can be tested without load. `text` and `image` requests are scripted on separate
queues, since a single turn can call both (a reply choosing `make-attempt`, whose
attempt then asks for an image) and the two must never be confused for one another.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sonavida.ports.models import ModelOutcome, ModelResult

_DEFAULT_TEXT = (
    '{"action": "do-nothing", "reason": "nothing calls to me yet.", '
    '"remember": {"importance": 1}, "nextTurnIn": "PT1H"}'
)

# The smallest possible valid PNG: a 1x1 transparent pixel.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "89000000017352474200aece1ce90000000d49444154789c626001000000ffff"
    "030000060005c9a4f10000000049454e44ae426082"
)


@dataclass
class ScriptedModels:
    """FIFO of scripted outcomes; once exhausted, answers with a default result."""

    default_text: str = _DEFAULT_TEXT
    _text_queue: deque[ModelOutcome] = field(default_factory=deque)
    _image_queue: deque[ModelOutcome] = field(default_factory=deque)
    calls: list[tuple[str, str]] = field(default_factory=list)

    def script(self, *outcomes: ModelOutcome) -> None:
        """Scripts the next `text` calls (a turn's own thinking, R-7's `Busy`/`Starting`
        answers included). Use `script_image` for `make-attempt`/`rework` outcomes."""
        self._text_queue.extend(outcomes)

    def script_text(self, *texts: str) -> None:
        self._text_queue.extend(
            ModelResult(text=t, image_bytes=None, settings_used={}) for t in texts
        )

    def script_image(self, *outcomes: ModelOutcome) -> None:
        self._image_queue.extend(outcomes)

    async def text(
        self,
        instructions: str,
        *,
        conversation: tuple[dict[str, str], ...] = (),
        images: tuple[dict[str, str], ...] = (),
    ) -> ModelOutcome:
        self.calls.append(("text", instructions))
        if self._text_queue:
            return self._text_queue.popleft()
        return ModelResult(text=self.default_text, image_bytes=None, settings_used={})

    async def image(
        self,
        description: str,
        *,
        avoid: str | None = None,
        size: tuple[int, int] = (1024, 1024),
    ) -> ModelOutcome:
        self.calls.append(("image", description))
        if self._image_queue:
            return self._image_queue.popleft()
        return ModelResult(text=None, image_bytes=TINY_PNG, settings_used={"size": size})
