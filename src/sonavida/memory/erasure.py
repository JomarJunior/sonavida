"""Erasure: forgetting a visitor's identity, never the memories that hold it (R-8, FR-032, FR-033).

Everything happens in one pass, and only then is `VACUUM` run, so the freed pages that
held the pseudonym and the display name are gone from the file's raw bytes, not just
unreferenced. Pieces are never touched (FR-033): only `entries` holds a visitor.
"""

from __future__ import annotations

from sonavida.memory.store import MemoryStore
from sonavida.memory.tokens import token_for


def erase_visitor(store: MemoryStore, pseudonym: str) -> None:
    conn = store.connection()
    rows = conn.execute(
        "SELECT id, text, reason, visitor_name FROM entries WHERE visitor_pseudonym = ?",
        (pseudonym,),
    ).fetchall()
    if not rows:
        return
    token = token_for(pseudonym)
    display_name = next((r["visitor_name"] for r in rows if r["visitor_name"]), None)
    for row in rows:
        new_text = row["text"].replace(token, "someone")
        new_reason = row["reason"].replace(token, "someone") if row["reason"] else row["reason"]
        if display_name:
            new_text = _scrub(new_text, display_name)
            new_reason = _scrub(new_reason, display_name) if new_reason else new_reason
        conn.execute(
            "UPDATE entries SET text = ?, reason = ?, visitor_pseudonym = NULL, "
            "visitor_name = NULL WHERE id = ?",
            (new_text, new_reason, row["id"]),
        )
    # FTS5 tombstones old segments rather than rewriting them in place; a full
    # rebuild is the only way to be sure no fragment of the old text survives
    # anywhere the index touches disk.
    conn.execute("INSERT INTO entries_fts(entries_fts) VALUES ('rebuild')")
    conn.commit()
    conn.execute("VACUUM")
    conn.commit()


def _scrub(text: str, display_name: str) -> str:
    """A case-insensitive, whole-string-preserving removal of a free-typed name (R-8)."""
    lowered = text.lower()
    target = display_name.lower()
    if target not in lowered:
        return text
    result = []
    i = 0
    while i < len(text):
        if lowered.startswith(target, i):
            result.append("someone")
            i += len(display_name)
        else:
            result.append(text[i])
            i += 1
    return "".join(result)
