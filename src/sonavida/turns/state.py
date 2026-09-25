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
    # True while `working_on`'s most recent successful attempt has outcome
    # `kept-as-final` (see actions/creation.py for why that is the reading of "a kept
    # attempt" that `finish` requires — contracts/turn-protocol.md).
    working_on_has_kept_attempt: bool = False
    # The most recently finished, not-yet-decided piece, if any. `submit` and `keep`
    # are proposed whenever at least one exists; the persona names which one in its
    # own reply (`details.piece`), so more than one waiting at once is handled
    # correctly even though only the most recent is reflected here for hints.
    finished_piece_pending_decision: str | None = None
    interrupted_piece: str | None = None
    waiting_for: str | None = None
    next_turn_at: datetime | None = None
    leaving_pending: bool = False
