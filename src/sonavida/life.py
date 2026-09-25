"""A persona's life: the turn loop, presence and leaving's first choice (R-6, R-11).

Only `set-presence`, `do-nothing` and `leave-the-museum` are dispatched here for the
MVP (Phase 3, User Story 1). The creation, showing and inbox actions the turn protocol
also offers are real seams, not yet built: `form-intention`, `make-attempt`,
`look-again`, `rework`, `finish` and `abandon` belong to T026 (Phase 4); `submit` and
`keep` to T032 (Phase 5); `continue-unfinished` to T036 (Phase 6). None of them is
reachable yet because nothing in Phase 1-3 ever starts a piece, so `working_on` stays
`None` and `form-intention` — though always proposed when "in the studio, nothing in
progress" — is simply never the action a Phase-3 run's model chooses to dispatch.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from miraveja_studiolink.messages.common import PersonaRef

from sonavida.actions.nothing import chose_nothing
from sonavida.actions.presence import set_presence
from sonavida.memory.store import MemoryStore
from sonavida.ports.clock import Clock
from sonavida.ports.models import Models
from sonavida.ports.studiolink import StudioLink
from sonavida.translate import translate
from sonavida.turns.prompt import build_prompt
from sonavida.turns.proposals import build_proposals, valid_actions
from sonavida.turns.reply import LostThread, TurnReply, get_reply
from sonavida.turns.state import TurnState

DEFAULT_NEXT_TURN = timedelta(hours=1)
STUDIO_LIMIT_WAIT = timedelta(minutes=30)
TIME_AWAY_MIN_GAP = timedelta(minutes=1)
RECALL_BUDGET = 20


def _describe_gap(gap: timedelta) -> str:
    days = gap.days
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''}"
    hours = gap.seconds // 3600
    if hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    minutes = gap.seconds // 60
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def _rebuild_state(store: MemoryStore) -> TurnState:
    entries = store.all_entries()
    state = TurnState()
    for entry in reversed(entries):
        if entry.kind == "presence":
            state.presence = entry.text  # type: ignore[assignment]
            break
    if entries and entries[-1].kind == "thinking-of-leaving":
        state.leaving_pending = True
    return state


class Life:
    """One persona's turn loop, hosted by `runtime.py`."""

    def __init__(
        self,
        *,
        store: MemoryStore,
        clock: Clock,
        models: Models,
        studiolink: StudioLink,
    ) -> None:
        self.store = store
        self.clock = clock
        self.models = models
        self.studiolink = studiolink
        self_record = store.read_self()
        self.persona_id = self_record.persona_id
        self.public_name = self_record.public_name
        self.self_knowledge = self_record.self_knowledge
        self.persona_ref = PersonaRef(
            personaId=uuid.UUID(self.persona_id), publicName=self.public_name
        )
        self.departed = self_record.departed_at is not None
        self.state = _rebuild_state(store)
        self._note_time_away_if_any()

    def _note_time_away_if_any(self) -> None:
        entries = self.store.all_entries()
        if not entries:
            return
        gap = self.clock.now() - entries[-1].at
        if gap > TIME_AWAY_MIN_GAP:
            self.store.append(
                at=self.clock.now(),
                kind="time-away",
                text=f"away for {_describe_gap(gap)}.",
                importance=2,
            )
            self.state.presence = "away"

    async def announce_departure(self) -> None:
        """FR-008: announce away before the Studio stops, on an orderly shutdown."""
        if self.departed:
            return
        now = self.clock.now()
        await set_presence(
            store=self.store,
            studiolink=self.studiolink,
            persona=self.persona_ref,
            state="away",
            reason="the studio is closing for now.",
            importance=1,
            at=now,
        )
        self.state.presence = "away"

    async def take_turn(self) -> timedelta:
        """One turn: propose, ask, validate, dispatch. Returns the wait before the next one."""
        now = self.clock.now()
        proposals = build_proposals(self.state, self.self_knowledge)
        recalled = self.store.recall(self._recall_query(), budget=RECALL_BUDGET)
        all_entries = self.store.all_entries()
        last_turn_at = all_entries[-1].at if all_entries else None
        prompt = build_prompt(
            self_knowledge=self.self_knowledge,
            now=now,
            presence=self.state.presence,
            last_turn_at=last_turn_at,
            working_on=self.state.working_on,
            recalled=recalled,
            proposals=proposals,
        )
        outcome = await get_reply(self.models, prompt.text, valid_actions=valid_actions(self.state))
        if isinstance(outcome, TurnReply):
            await self._dispatch(outcome, now)
            return outcome.next_turn_in
        if isinstance(outcome, LostThread):
            self.store.append(
                at=now,
                kind="lost-thread",
                text="I lost my train of thought.",
                importance=1,
            )
            return outcome.rest_for
        # A Studio limit reached while the persona was only trying to think (R-7).
        translated = translate(outcome)
        self.store.append(at=now, kind=translated.kind, text=translated.situation, importance=2)
        return STUDIO_LIMIT_WAIT

    def _recall_query(self) -> str:
        return str(self.self_knowledge.get("workTendency", ""))

    async def _dispatch(self, reply: TurnReply, now: datetime) -> None:
        action = reply.action
        if action != "leave-the-museum":
            self.state.leaving_pending = False

        if action == "set-presence":
            new_state = reply.details["presence"]
            await set_presence(
                store=self.store,
                studiolink=self.studiolink,
                persona=self.persona_ref,
                state=new_state,  # type: ignore[arg-type]
                reason=reply.reason,
                importance=reply.importance,
                at=now,
            )
            self.state.presence = new_state  # type: ignore[assignment]
            return

        if action == "do-nothing":
            chose_nothing(
                store=self.store, reason=reply.reason, importance=reply.importance, at=now
            )
            return

        if action == "leave-the-museum":
            await self._leave(reply, now)
            return

        raise NotImplementedError(
            f"{action!r} is proposed by the turn protocol but not dispatched before "
            "Phase 4 (creation, T026), Phase 5 (showing, T032) or Phase 6 (inbox, T036)."
        )

    async def _leave(self, reply: TurnReply, now: datetime) -> None:
        if not self.state.leaving_pending:
            self.store.append(
                at=now,
                kind="thinking-of-leaving",
                text="thinking of leaving the museum.",
                reason=reply.reason,
                importance=reply.importance,
            )
            self.state.leaving_pending = True
            return
        self.store.append(
            at=now,
            kind="departed",
            text="departed the museum.",
            reason=reply.reason,
            importance=reply.importance,
        )
        self.store.record_departure(now)
        await self.studiolink.announce_presence(self.persona_ref, "away")
        self.state.leaving_pending = False
        self.departed = True
