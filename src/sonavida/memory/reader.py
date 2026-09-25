"""Read-only access to a persona's memory, for the team's own eyes on the Studio (R-12).

Every function here opens the file `mode=ro` (`MemoryStore`'s own read-only mode) and
never calls a method that could write to it. There is no command, API or server that
writes to memory from here (FR-035, FR-036); reading from outside the Studio is not
possible because nothing here ever listens on a network (US5 scenario 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sonavida.memory.store import Entry, MemoryStore
from sonavida.memory.tokens import render_tokens

# Plain-language phrases for entry kinds that need one; kinds not listed here (mostly
# already prose in the persona's own words) are printed as `entry.text` alone.
KIND_PHRASES: dict[str, str] = {
    "seed": "remembered from before",
    "self-aware": "",
    "presence": "presence changed to",
    "time-away": "",
    "intention": "formed the intention",
    "attempt": "made an attempt",
    "attempt-seen": "looked at an attempt and saw",
    "finished": "finished a piece, titled",
    "abandoned": "abandoned the piece",
    "kept": "kept the piece",
    "submitted": "submitted the piece",
    "verdict": "the gate's verdict",
    "experience": "",
    "studio-not-ready": "",
    "interrupted": "",
    "attempt-failed": "",
    "lost-thread": "",
    "thinking-of-leaving": "",
    "departed": "",
    "chose-nothing": "",
}


@dataclass(frozen=True)
class ReadableEntry:
    at: datetime
    line: str


def _line_for(entry: Entry) -> str:
    text = render_tokens(entry.text, entry.visitor_pseudonym, entry.visitor_name)
    phrase = KIND_PHRASES.get(entry.kind, "")
    body = f"{phrase}: {text}" if phrase else text
    if entry.reason:
        body = f"{body} — because {entry.reason}"
    when = entry.at.isoformat(timespec="minutes")
    return f"[{when}] {body}"


def read_memory(
    path: Path, *, since: date | None = None, until: date | None = None
) -> list[ReadableEntry]:
    """The persona's memory, in time order, plain language, each decision beside its
    reason; visitors are always names or "someone" (R-8), never a raw pseudonym."""
    with MemoryStore(path, mode="ro") as store:
        entries = store.all_entries()
    readable = []
    for entry in entries:
        if since is not None and entry.at.date() < since:
            continue
        if until is not None and entry.at.date() > until:
            continue
        readable.append(ReadableEntry(at=entry.at, line=_line_for(entry)))
    return readable


def read_pieces(path: Path) -> list[str]:
    """Every piece, its state history's current state, title, statement and labels."""
    with MemoryStore(path, mode="ro") as store:
        piece_ids: list[str] = []
        for entry in store.all_entries():
            if entry.piece_id and entry.piece_id not in piece_ids:
                piece_ids.append(entry.piece_id)
        lines = []
        for piece_id in piece_ids:
            piece = store.get_piece(piece_id)
            title = piece.title or "(untitled)"
            labels = ", ".join(sorted(piece.labels)) if piece.labels else "none"
            lines.append(f"{title} — {piece.state} (labels: {labels})")
            if piece.statement:
                lines.append(f'  "{piece.statement}"')
        return lines
