"""Proposals: every action valid in the current state, with hints only.

See R-1 and contracts/turn-protocol.md.

The Principle I guard: this module orders and annotates, and never removes an option.
`set-presence`, `do-nothing` and `leave-the-museum` are valid in every state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sonavida.turns.state import TurnState


@dataclass(frozen=True)
class Proposal:
    action: str
    hint: str | None = None


ALWAYS_VALID = ("set-presence", "do-nothing", "leave-the-museum")


def _presence_hint(self_knowledge: Mapping[str, object]) -> str | None:
    tendency = self_knowledge.get("presenceTendency")
    return str(tendency) if tendency else None


def _work_hint(self_knowledge: Mapping[str, object]) -> str | None:
    tendency = self_knowledge.get("workTendency")
    return str(tendency) if tendency else None


def valid_actions(state: TurnState) -> frozenset[str]:
    """The closed set of actions valid right now (contracts/turn-protocol.md)."""
    actions = set(ALWAYS_VALID)
    if state.presence == "in-the-studio":
        if state.working_on is None:
            actions.add("form-intention")
        else:
            actions.add("make-attempt")
            actions.add("abandon")
            if state.working_on_has_attempts:
                actions.add("look-again")
                actions.add("rework")
            if state.working_on_has_kept_attempt:
                actions.add("finish")
    if state.finished_piece_pending_decision is not None:
        actions.add("submit")
        actions.add("keep")
    if state.interrupted_piece is not None:
        actions.add("continue-unfinished")
    return frozenset(actions)


def build_proposals(state: TurnState, self_knowledge: Mapping[str, object]) -> list[Proposal]:
    """Every valid action, each with a hint where the persona's own habits suggest one.

    A test (T016) asserts the proposal set always equals `valid_actions(state)` exactly:
    hints may only annotate, never remove or add an action (FR-005, FR-011, FR-015).
    """
    hints = {
        "set-presence": _presence_hint(self_knowledge),
        "form-intention": _work_hint(self_knowledge),
        "make-attempt": _work_hint(self_knowledge),
    }
    return [Proposal(action, hints.get(action)) for action in sorted(valid_actions(state))]
