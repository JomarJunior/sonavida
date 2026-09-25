"""The prompt builder: what a turn gives the model (R-10, contracts/turn-protocol.md).

Recalled entries are rendered one by one, in time order; nothing here counts, ranks or
totals them (FR-027, R-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sonavida.memory.store import Entry
from sonavida.memory.tokens import render_tokens
from sonavida.turns.proposals import Proposal

REPLY_SCHEMA = """\
Answer with exactly one JSON object, nothing else:
{
  "action": "<one of the actions listed above>",
  "details": { ...exactly the fields that action needs, no others... },
  "reason": "<required, in your own words>",
  "remember": { "importance": <1-5, your own sense of how much this matters> },
  "nextTurnIn": "<an ISO 8601 duration, any length you want, e.g. PT2H>"
}
"""


def _time_away_line(now: datetime, last_turn_at: datetime | None) -> str:
    if last_turn_at is None:
        return ""
    gap = now - last_turn_at
    if gap < timedelta(minutes=1):
        return ""
    return f"It has been {_describe_duration(gap)} since I was last in the studio.\n"


def _describe_duration(delta: timedelta) -> str:
    days = delta.days
    hours = delta.seconds // 3600
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''}"
    if hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    minutes = delta.seconds // 60
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


@dataclass(frozen=True)
class Prompt:
    text: str


def build_prompt(
    *,
    self_knowledge: dict[str, object],
    now: datetime,
    presence: str,
    last_turn_at: datetime | None,
    working_on: str | None,
    recalled: list[Entry],
    proposals: list[Proposal],
) -> Prompt:
    lines: list[str] = []
    lines.append("Who I am:")
    for key in ("about", "speech", "temperament", "presenceTendency", "workTendency"):
        value = self_knowledge.get(key)
        if value:
            lines.append(f"- {value}")
    lines.append("")
    lines.append("Where I am:")
    lines.append(f"It is {now.isoformat(timespec='minutes')}. I am currently {presence}.")
    away_line = _time_away_line(now, last_turn_at)
    if away_line:
        lines.append(away_line.strip())
    lines.append("")
    lines.append("What I am doing:")
    lines.append(f"working on {working_on}" if working_on else "nothing in progress right now.")
    lines.append("")
    lines.append("What I remember:")
    if recalled:
        for entry in recalled:
            # Strictly one by one, tokens rendered to names; never aggregated (R-10, FR-027).
            text = render_tokens(entry.text, entry.visitor_pseudonym, entry.visitor_name)
            reason = f" — {entry.reason}" if entry.reason else ""
            lines.append(f"- [{entry.at.isoformat(timespec='minutes')}] {text}{reason}")
    else:
        lines.append("(nothing recalled for this moment)")
    lines.append("")
    lines.append("What I could do now:")
    for proposal in proposals:
        hint = f" ({proposal.hint})" if proposal.hint else ""
        lines.append(f"- {proposal.action}{hint}")
    lines.append("")
    lines.append("How to answer:")
    lines.append(REPLY_SCHEMA)
    return Prompt("\n".join(lines))
