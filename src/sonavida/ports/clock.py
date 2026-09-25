"""Time, as a port (R-6, FR-039).

`RealClock` uses the Studio's own local time. `SimulatedClock` advances instantly to
the next due turn, so a simulated week of several personas' lives runs in the time
their turns take to compute, and repeats exactly given the same seed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def wait_until(self, when: datetime) -> None: ...


class RealClock:
    """The Studio's own local time."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def wait_until(self, when: datetime) -> None:
        delay = (when - self.now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)


@dataclass
class _Waiter:
    when: datetime
    event: asyncio.Event = field(default_factory=asyncio.Event)


class SimulatedClock:
    """A seeded clock that jumps straight to the next due turn.

    Every persona task that lives on this clock calls `join()` once, before it starts
    waiting, and `leave()` when it stops for good (departure, shutdown). Time advances
    only once every joined task is blocked in `wait_until`, to the earliest of their
    requested times — nothing is simulated in between, so a week of turns costs only
    the time it takes to compute them.
    """

    def __init__(self, start: datetime, seed: int) -> None:
        self._now = start
        self.seed = seed
        self._registered = 0
        self._waiters: list[_Waiter] = []

    def now(self) -> datetime:
        return self._now

    def join(self) -> None:
        self._registered += 1

    def leave(self) -> None:
        self._registered = max(0, self._registered - 1)
        self._advance_if_ready()

    async def wait_until(self, when: datetime) -> None:
        if when <= self._now:
            return
        waiter = _Waiter(when)
        self._waiters.append(waiter)
        self._advance_if_ready()
        await waiter.event.wait()

    def _advance_if_ready(self) -> None:
        if not self._waiters or len(self._waiters) < self._registered:
            return
        target = min(w.when for w in self._waiters)
        if target > self._now:
            self._now = target
        due = [w for w in self._waiters if w.when <= self._now]
        self._waiters = [w for w in self._waiters if w.when > self._now]
        for waiter in due:
            waiter.event.set()
