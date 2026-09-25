"""Studio conditions into persona situations (R-7, FR-029 to FR-031).

The only place **🧠 ModelMora**'s answers turn into something a persona is told. No
model name, error code or queue position ever crosses this boundary; a wait becomes
a time of day, never a number of requests ahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sonavida.ports.models import Busy, CannotServe, Failed, ModelOutcome, Starting, Stopping

# Entry kinds this module produces (data-model.md).
STUDIO_NOT_READY = "studio-not-ready"
INTERRUPTED = "interrupted"
ATTEMPT_FAILED = "attempt-failed"


@dataclass(frozen=True)
class Translated:
    kind: str
    situation: str


def _time_of_day(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def translate(outcome: ModelOutcome) -> Translated:
    """The in-character situation a persona sees for an outcome that was not a result."""
    if isinstance(outcome, Busy | Starting):
        if outcome.retry_at is not None:
            situation = (
                f"the studio is not ready; it may be ready around {_time_of_day(outcome.retry_at)}"
            )
        else:
            situation = "the studio is not ready right now"
        return Translated(STUDIO_NOT_READY, situation)
    if isinstance(outcome, Stopping):
        return Translated(INTERRUPTED, "the work was interrupted")
    if isinstance(outcome, Failed | CannotServe):
        return Translated(ATTEMPT_FAILED, "the attempt did not come out")
    raise TypeError(f"not a situation to translate: {outcome!r}")
