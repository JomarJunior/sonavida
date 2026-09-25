"""The `Perception` port (FR-013, R-9).

Real implementation: **💬 DescriDiva** (roadmap 005), a seam left for that spec.
Until then, `standins/perception.py` (T027) provides it. A persona sees its own
attempts only through this one neutral description.
"""

from __future__ import annotations

from typing import Protocol


class Perception(Protocol):
    async def describe(self, image_bytes: bytes) -> str: ...
