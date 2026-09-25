"""A persona's life: the turn loop, presence, making, showing and leaving.

R-6, R-9, R-11, FR-007, FR-010 to FR-024.

`continue-unfinished` has no memory entry of its own in the data model's closed kind
list: resuming is simply not remembered as a distinct event, only what the persona
does next (a further `attempt`, `rework`, or `abandoned`) is.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from miraveja_studiolink.messages.common import PersonaRef

from sonavida import inbox
from sonavida.actions import creation, showing
from sonavida.actions.nothing import chose_nothing
from sonavida.actions.presence import set_presence
from sonavida.memory.store import MemoryStore
from sonavida.ports.clock import Clock
from sonavida.ports.gate import AiGate
from sonavida.ports.models import ModelOutcome, Models, Stopping
from sonavida.ports.perception import Perception
from sonavida.ports.studiolink import StudioLink
from sonavida.translate import translate
from sonavida.turns.prompt import build_prompt
from sonavida.turns.proposals import build_proposals, valid_actions
from sonavida.turns.reply import LostThread, TurnReply, get_reply
from sonavida.turns.state import TurnState

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

    in_progress = store.pieces_in_state("in-progress")
    if in_progress:
        piece = in_progress[0]
        attempts = store.attempts_for(piece.id)
        if attempts and attempts[-1].outcome == "interrupted":
            state.interrupted_piece = piece.id
        else:
            state.working_on = piece.id
            state.working_on_has_attempts = bool(attempts)
            state.working_on_has_kept_attempt = any(a.outcome == "kept-as-final" for a in attempts)
    finished = store.pieces_in_state("finished")
    if finished:
        state.finished_piece_pending_decision = finished[0].id
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
        perception: Perception,
        gate: AiGate,
    ) -> None:
        self.store = store
        self.clock = clock
        self.models = models
        self.studiolink = studiolink
        self.perception = perception
        self.gate = gate
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

    def _piece_dir(self, piece_id: str) -> Path:
        return self.store.path.parent / "pieces" / piece_id

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
        """One turn: collect, propose, ask, validate, dispatch."""
        now = self.clock.now()
        persona_uuid = uuid.UUID(self.persona_id)
        await inbox.collect_experiences(self.store, self.studiolink, persona_uuid, now)
        await inbox.collect_erasure_notices(self.store, self.studiolink, persona_uuid)

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
            await self._set_presence(reply, now)
        elif action == "do-nothing":
            await self._do_nothing(reply, now)
        elif action == "form-intention":
            await self._form_intention(reply, now)
        elif action == "make-attempt":
            await self._make_attempt(reply, now)
        elif action == "look-again":
            await self._look_again(reply, now)
        elif action == "rework":
            await self._rework(reply, now)
        elif action == "finish":
            await self._finish(reply, now)
        elif action == "abandon":
            await self._abandon(reply, now)
        elif action == "continue-unfinished":
            await self._continue_unfinished(reply, now)
        elif action == "keep":
            await self._keep(reply, now)
        elif action == "submit":
            await self._submit(reply, now)
        elif action == "leave-the-museum":
            await self._leave(reply, now)
        else:
            raise NotImplementedError(f"{action!r} is proposed but has no dispatcher")

    async def _set_presence(self, reply: TurnReply, now: datetime) -> None:
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

    async def _do_nothing(self, reply: TurnReply, now: datetime) -> None:
        chose_nothing(store=self.store, reason=reply.reason, importance=reply.importance, at=now)

    async def _form_intention(self, reply: TurnReply, now: datetime) -> None:
        piece_id = creation.form_intention(
            store=self.store,
            intention=str(reply.details["intention"]),
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )
        self.state.working_on = piece_id
        self.state.working_on_has_attempts = False
        self.state.working_on_has_kept_attempt = False

    async def _make_attempt(self, reply: TurnReply, now: datetime) -> None:
        assert self.state.working_on is not None
        piece_id = self.state.working_on
        _attempt_id, failure = await creation.make_attempt(
            store=self.store,
            models=self.models,
            self_knowledge=self.self_knowledge,
            piece_dir=self._piece_dir(piece_id),
            piece_id=piece_id,
            ask=str(reply.details["ask"]),
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )
        self._refresh_working_on(piece_id, interrupted=failure)

    async def _look_again(self, reply: TurnReply, now: datetime) -> None:
        assert self.state.working_on is not None
        await creation.look_again(
            store=self.store,
            perception=self.perception,
            piece_id=self.state.working_on,
            attempt_id=int(str(reply.details["attempt"])),
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )

    async def _rework(self, reply: TurnReply, now: datetime) -> None:
        assert self.state.working_on is not None
        piece_id = self.state.working_on
        _attempt_id, failure = await creation.rework(
            store=self.store,
            models=self.models,
            self_knowledge=self.self_knowledge,
            piece_dir=self._piece_dir(piece_id),
            piece_id=piece_id,
            old_attempt_id=int(str(reply.details["attempt"])),
            ask=str(reply.details["ask"]),
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )
        self._refresh_working_on(piece_id, interrupted=failure)

    def _refresh_working_on(self, piece_id: str, *, interrupted: ModelOutcome | None) -> None:
        attempts = self.store.attempts_for(piece_id)
        self.state.working_on_has_attempts = bool(attempts)
        self.state.working_on_has_kept_attempt = any(a.outcome == "kept-as-final" for a in attempts)
        if interrupted is not None:
            translated = translate(interrupted)
            self.store.append(
                at=self.clock.now(),
                kind=translated.kind,
                text=translated.situation,
                importance=2,
                piece_id=piece_id,
            )
            if isinstance(interrupted, Stopping):
                self.state.interrupted_piece = piece_id
                self.state.working_on = None

    async def _finish(self, reply: TurnReply, now: datetime) -> None:
        assert self.state.working_on is not None
        piece_id = self.state.working_on
        creation.finish(
            store=self.store,
            piece_id=piece_id,
            attempt_id=int(str(reply.details["attempt"])),
            title=str(reply.details["title"]),
            statement=str(reply.details["statement"]),
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )
        self.state.working_on = None
        self.state.working_on_has_attempts = False
        self.state.working_on_has_kept_attempt = False
        self.state.finished_piece_pending_decision = piece_id

    async def _abandon(self, reply: TurnReply, now: datetime) -> None:
        assert self.state.working_on is not None
        creation.abandon(
            store=self.store,
            piece_id=self.state.working_on,
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )
        self.state.working_on = None
        self.state.working_on_has_attempts = False
        self.state.working_on_has_kept_attempt = False

    async def _continue_unfinished(self, reply: TurnReply, now: datetime) -> None:
        piece_id = str(reply.details["piece"])
        self.state.interrupted_piece = None
        self.state.working_on = piece_id
        attempts = self.store.attempts_for(piece_id)
        self.state.working_on_has_attempts = bool(attempts)
        self.state.working_on_has_kept_attempt = any(a.outcome == "kept-as-final" for a in attempts)

    async def _keep(self, reply: TurnReply, now: datetime) -> None:
        piece_id = str(reply.details["piece"])
        showing.keep(
            store=self.store,
            piece_id=piece_id,
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )
        if self.state.finished_piece_pending_decision == piece_id:
            self.state.finished_piece_pending_decision = None

    async def _submit(self, reply: TurnReply, now: datetime) -> None:
        piece_id = str(reply.details["piece"])
        raw_labels = reply.details.get("suggestedLabels", [])
        assert isinstance(raw_labels, list)
        suggested = frozenset(str(label) for label in raw_labels)
        showing.submit(
            store=self.store,
            piece_id=piece_id,
            suggested_labels=suggested,
            reason=reply.reason,
            importance=reply.importance,
            at=now,
        )
        if self.state.finished_piece_pending_decision == piece_id:
            self.state.finished_piece_pending_decision = None
        await self._ask_the_gate(piece_id, now)

    async def _ask_the_gate(self, piece_id: str, now: datetime) -> None:
        piece = self.store.get_piece(piece_id)
        assert piece.image_path is not None
        image_bytes = Path(piece.image_path).read_bytes()
        neutral_description = await self.perception.describe(image_bytes)
        assert piece.title is not None
        assert piece.statement is not None
        verdict = await self.gate.submit(
            persona_id=uuid.UUID(self.persona_id),
            public_name=self.public_name,
            piece_id=uuid.UUID(piece_id),
            title=piece.title,
            statement=piece.statement,
            image_bytes=image_bytes,
            neutral_description=neutral_description,
            suggested_labels=piece.suggested_labels,
        )
        if verdict.accepted:
            self.store.update_piece(piece_id, state="accepted", labels=verdict.labels)
            self.store.append(
                at=now,
                kind="verdict",
                text="the piece was accepted.",
                reason=verdict.reason,
                importance=2,
                piece_id=piece_id,
            )
        else:
            self.store.update_piece(piece_id, state="rejected", labels=verdict.labels)
            self.store.append(
                at=now,
                kind="verdict",
                text=verdict.feedback or "the piece was rejected.",
                reason=verdict.reason,
                importance=2,
                piece_id=piece_id,
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
