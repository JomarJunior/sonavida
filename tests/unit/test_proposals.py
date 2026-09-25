"""T016: the proposal set always equals the valid-action set for the state (R-1)."""

from __future__ import annotations

from sonavida.turns.proposals import ALWAYS_VALID, build_proposals, valid_actions
from sonavida.turns.state import TurnState

SELF_KNOWLEDGE = {
    "presenceTendency": "tends to be in the studio in the evenings.",
    "workTendency": "works slowly and rarely exhibits.",
}


def _reachable_states() -> list[TurnState]:
    return [
        TurnState(presence="away"),
        TurnState(presence="resting"),
        TurnState(presence="in-the-studio"),
        TurnState(presence="in-the-studio", working_on="piece-1"),
        TurnState(presence="in-the-studio", working_on="piece-1", working_on_has_attempts=True),
        TurnState(
            presence="in-the-studio",
            working_on="piece-1",
            working_on_has_attempts=True,
            working_on_has_kept_attempt=True,
        ),
        TurnState(presence="in-the-studio", finished_piece_pending_decision="piece-2"),
        TurnState(presence="resting", finished_piece_pending_decision="piece-2"),
        TurnState(presence="away", interrupted_piece="piece-3"),
        TurnState(presence="in-the-studio", leaving_pending=True),
    ]


def test_proposal_set_equals_valid_action_set_for_every_reachable_state() -> None:
    for state in _reachable_states():
        proposed = {p.action for p in build_proposals(state, SELF_KNOWLEDGE)}
        assert proposed == valid_actions(state)


def test_always_valid_actions_are_always_present() -> None:
    for state in _reachable_states():
        proposed = {p.action for p in build_proposals(state, SELF_KNOWLEDGE)}
        assert set(ALWAYS_VALID) <= proposed


def test_hints_only_annotate_and_never_remove_an_option() -> None:
    state = TurnState(presence="in-the-studio")
    with_hints = {p.action for p in build_proposals(state, SELF_KNOWLEDGE)}
    without_hints = {p.action for p in build_proposals(state, {})}
    assert with_hints == without_hints == valid_actions(state)


def test_hints_come_only_from_self_knowledge() -> None:
    state = TurnState(presence="in-the-studio")
    proposals = {p.action: p.hint for p in build_proposals(state, SELF_KNOWLEDGE)}
    assert proposals["set-presence"] == SELF_KNOWLEDGE["presenceTendency"]
    assert proposals["form-intention"] == SELF_KNOWLEDGE["workTendency"]
    assert proposals["do-nothing"] is None


def test_form_intention_only_when_nothing_in_progress() -> None:
    idle = valid_actions(TurnState(presence="in-the-studio"))
    working = valid_actions(TurnState(presence="in-the-studio", working_on="piece-1"))
    assert "form-intention" in idle
    assert "form-intention" not in working


def test_finish_requires_a_kept_attempt() -> None:
    no_attempts = valid_actions(TurnState(presence="in-the-studio", working_on="piece-1"))
    with_attempts = valid_actions(
        TurnState(presence="in-the-studio", working_on="piece-1", working_on_has_attempts=True)
    )
    with_kept = valid_actions(
        TurnState(
            presence="in-the-studio",
            working_on="piece-1",
            working_on_has_attempts=True,
            working_on_has_kept_attempt=True,
        )
    )
    assert "finish" not in no_attempts
    assert "finish" not in with_attempts
    assert "finish" in with_kept
