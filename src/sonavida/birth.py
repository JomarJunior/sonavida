"""Bringing a persona alive from its definition, once (FR-001, FR-002, R-3, R-4).

The definition is read here and nowhere else. What comes alive is copied into the
persona's own memory file as its `self` record and its first memories; a later change
to the definition file can never reach a living persona (FR-002), because nothing
here is ever called a second time for the same persona.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from sonavida.memory.store import MemoryStore
from sonavida.ports import vault
from sonavida.ports.clock import Clock
from sonavida.ports.vault import Definition

SELF_AWARE_TEXT = (
    "I am an AI. The life I carry, however human-shaped, is a story I carry — not a "
    "claim to have been born human."
)


def persona_memory_path(home: Path, persona_id: str) -> Path:
    return home / "personas" / persona_id / "memory.sqlite"


def is_alive(home: Path, persona_id: str) -> bool:
    """Known to be born when its memory file exists (R-3)."""
    return MemoryStore.exists(persona_memory_path(home, persona_id))


def _reopen(memory_path: Path) -> MemoryStore:
    """A persona already alive, continuing from memory.

    A departed persona's file is read-only on disk (FR-040, runtime.py); opened
    read-write regardless, that open itself would fail before `runtime.host` ever
    gets the chance to refuse it cleanly as `departed`. Peeking read-only first tells
    the two cases apart.
    """
    with MemoryStore(memory_path, mode="ro") as peek:
        departed = peek.read_self().departed_at is not None
    if departed:
        return MemoryStore(memory_path, mode="ro")
    return MemoryStore(memory_path)


def _self_knowledge(definition: Definition) -> dict[str, object]:
    return {
        "about": definition.identity.about,
        "selfUnderstanding": definition.identity.self_understanding,
        "tasteDrawnTo": definition.taste.drawn_to,
        "themes": list(definition.taste.themes),
        "stylesAndMedia": definition.taste.styles_and_media,
        "dislikes": definition.taste.dislikes,
        "speech": definition.voice.speech,
        "temperament": definition.voice.temperament,
        "presenceTendency": definition.tendencies.presence,
        "workTendency": definition.tendencies.work,
        "cares": list(definition.cares),
        "craft": definition.craft,
        "selfImage": definition.self_image,
        "lore": [
            {"name": n.name, "is": n.is_}
            for n in (definition.lore.names if definition.lore else ())
        ],
    }


def _render_shared_past(
    happened: str, participants: tuple[str, ...], own_id: str, names: Mapping[str, str]
) -> str:
    text = happened.strip()
    for index, participant_id in enumerate(participants, start=1):
        token = f"{{{index}}}"
        replacement = (
            "I" if participant_id == own_id else names.get(participant_id, "someone I once knew")
        )
        text = text.replace(token, replacement)
    return text


def public_names_from_pasts(pasts_listing: list[dict[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for story in pasts_listing:
        for participant in story["participants"]:
            public_name = participant.get("publicName")
            if public_name:
                names[participant["id"]] = public_name
    return names


def _birth(
    definition: Definition,
    *,
    home: Path,
    clock: Clock,
    known_public_names: Mapping[str, str],
) -> MemoryStore:
    persona_id = definition.identity.id
    memory_path = persona_memory_path(home, persona_id)
    if MemoryStore.exists(memory_path):
        # Already alive: continue from memory. The definition is not read a second
        # time (the caller above chose not to load it in this branch either).
        return _reopen(memory_path)

    store = MemoryStore(memory_path)
    now = clock.now()
    store.write_self(
        persona_id=persona_id,
        public_name=definition.identity.public_name,
        self_knowledge=_self_knowledge(definition),
        born_at=now,
    )
    store.append(at=now, kind="self-aware", text=SELF_AWARE_TEXT, importance=5)
    for seed in definition.seed_memories:
        store.append(at=now, kind="seed", text=seed.happened.strip(), importance=3)
    for past in definition.shared_pasts:
        text = _render_shared_past(past.happened, past.participants, persona_id, known_public_names)
        store.append(at=now, kind="seed", text=text, importance=3)
    return store


def birth_resident(
    persona_id: str, path: Path, cofrealma_root: Path, *, home: Path, clock: Clock
) -> MemoryStore:
    """Bring a resident persona alive (FR-001, FR-003).

    `persona_id` comes from the birth ledger (`vault.read_ledger`), never from the
    definition file itself, so a persona already alive never causes the file to be
    opened at all (FR-002). Refusals: see `vault.load_resident`.
    """
    if is_alive(home, persona_id):
        return _reopen(persona_memory_path(home, persona_id))
    definition = vault.load_resident(path, cofrealma_root)
    names = public_names_from_pasts(vault.list_pasts(cofrealma_root))
    return _birth(definition, home=home, clock=clock, known_public_names=names)


def birth_synthetic(
    persona_id: str,
    path: Path,
    *,
    home: Path,
    clock: Clock,
    known_public_names: Mapping[str, str] = MappingProxyType({}),
) -> MemoryStore:
    """Bring a synthetic persona alive, for tests and simulated runs only (FR-037)."""
    if is_alive(home, persona_id):
        return _reopen(persona_memory_path(home, persona_id))
    definition = vault.load_synthetic(path)
    return _birth(definition, home=home, clock=clock, known_public_names=known_public_names)
