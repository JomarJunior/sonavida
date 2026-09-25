"""Turn state: in memory only, rebuilt from `entries` on start (data-model.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Presence = Literal["in-the-studio", "resting", "away"]


@dataclass
class TurnState:
    presence: Presence = "away"
    working_on: str | None = None
    working_on_has_attempts: bool = False
    working_on_has_kept_attempt: bool = False
    finished_piece_pending_decision: str | None = None
    interrupted_piece: str | None = None
    waiting_for: str | None = None
    next_turn_at: datetime | None = None
    leaving_pending: bool = False
