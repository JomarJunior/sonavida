"""Hosting every living persona in one process: locks, shutdown, departure (R-5, FR-004,
FR-008, FR-040).

`host()` is where "one place at a time" is enforced (FR-004): an exclusive
`fcntl.flock` per persona, held for as long as it is alive, and where a persona already
recorded as departed is refused. Once a persona's own choice completes its departure
(`actions/leaving.py`), its memory file is set read-only on disk before its lock is
released, so nothing — not even a bug elsewhere in the process — can write to it again.
"""

from __future__ import annotations

import asyncio
import fcntl
from dataclasses import dataclass
from pathlib import Path

from sonavida.life import Life
from sonavida.memory.store import MemoryStore
from sonavida.ports.clock import Clock
from sonavida.ports.gate import AiGate
from sonavida.ports.models import Models
from sonavida.ports.perception import Perception
from sonavida.ports.studiolink import StudioLink


class AlreadyAlive(Exception):
    """FR-004: a persona lives in one place at a time."""


class Departed(Exception):
    """FR-040: a departed persona is never brought alive again."""


def lock_path(home: Path, persona_id: str) -> Path:
    return home / "personas" / persona_id / "lock"


class PersonaLock:
    """An exclusive, non-blocking file lock for as long as a persona is alive (R-5)."""

    def __init__(self, home: Path, persona_id: str) -> None:
        self.path = lock_path(home, persona_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            raise AlreadyAlive(persona_id) from None

    def release(self) -> None:
        fcntl.flock(self._file, fcntl.LOCK_UN)
        self._file.close()


@dataclass
class HostedPersona:
    life: Life
    lock: PersonaLock
    task: asyncio.Task[None]


class Runtime:
    """Hosts every living persona as its own asyncio task; nothing of one persona ever
    reaches another (FR-041)."""

    def __init__(
        self,
        *,
        home: Path,
        clock: Clock,
        models: Models,
        studiolink: StudioLink,
        perception: Perception,
        gate: AiGate,
    ) -> None:
        self.home = home
        self.clock = clock
        self.models = models
        self.studiolink = studiolink
        self.perception = perception
        self.gate = gate
        self.hosted: dict[str, HostedPersona] = {}
        self._stopping = asyncio.Event()

    def host(self, store: MemoryStore, persona_id: str) -> Life:
        if persona_id in self.hosted:
            raise AlreadyAlive(persona_id)
        if store.read_self().departed_at is not None:
            store.close()
            raise Departed(persona_id)
        lock = PersonaLock(self.home, persona_id)
        life = Life(
            store=store,
            clock=self.clock,
            models=self.models,
            studiolink=self.studiolink,
            perception=self.perception,
            gate=self.gate,
        )
        joinable = getattr(self.clock, "join", None)
        if joinable is not None:
            joinable()
        task = asyncio.create_task(self._run_one(life))
        self.hosted[persona_id] = HostedPersona(life=life, lock=lock, task=task)
        return life

    async def _run_one(self, life: Life) -> None:
        try:
            while not life.departed and not self._stopping.is_set():
                delta = await life.take_turn()
                if life.departed:
                    break
                next_at = self.clock.now() + delta
                stop_wait = asyncio.ensure_future(self._stopping.wait())
                clock_wait = asyncio.ensure_future(self.clock.wait_until(next_at))
                _, pending = await asyncio.wait(
                    {stop_wait, clock_wait}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
        finally:
            leaveable = getattr(self.clock, "leave", None)
            if leaveable is not None:
                leaveable()
            if life.departed:
                path = life.store.path
                life.store.close()
                path.chmod(0o444)
            else:
                await life.announce_departure()
            self.hosted[life.persona_id].lock.release()

    async def shutdown(self) -> None:
        """FR-008: announce every living persona as away, in order, before stopping."""
        self._stopping.set()
        for hosted in self.hosted.values():
            await hosted.task
