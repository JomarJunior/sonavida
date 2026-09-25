"""The visitor token (R-8): `entries.text`/`reason` may embed `⟨v:pseudonym⟩`.

Stored as a token, never a name, so an erasure can remove the identity everywhere it
appears without rewriting the persona's own reflections word by word. Rendered to a
name only when a turn or the team reads the memory.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"⟨v:([A-Za-z0-9_-]+)⟩")


def token_for(pseudonym: str) -> str:
    return f"⟨v:{pseudonym}⟩"


def render_tokens(text: str, visitor_pseudonym: str | None, visitor_name: str | None) -> str:
    """The token replaced by the visitor's current name, or "someone" once erased or
    for any token this entry's own columns no longer name (defensive)."""
    if visitor_pseudonym is not None:
        text = text.replace(token_for(visitor_pseudonym), visitor_name or "someone")
    return _TOKEN_RE.sub("someone", text)
