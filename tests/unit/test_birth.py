"""T014: birth from a definition alone, once, with shared pasts in the first person."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida import birth
from sonavida.ports.clock import Clock
from sonavida.ports.vault import DefinitionRefused

from ..conftest import IVO_ID, PELLAM_ID, as_resident, make_scratch_vault


class _FixedClock:
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when

    async def wait_until(self, when: datetime) -> None:  # pragma: no cover - unused here
        raise NotImplementedError


@pytest.fixture
def clock() -> Clock:
    return _FixedClock(datetime(2026, 1, 1, tzinfo=UTC))


def test_birth_copies_self_knowledge_and_seeds_memory(
    tmp_path: Path, examples: Path, clock: Clock
) -> None:
    home = tmp_path / "home"
    path = examples / "pellam-quist.persona.yaml"
    store = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)

    self_record = store.read_self()
    assert self_record.public_name == "Pellam Quist"
    assert any("harbor" in c.lower() for c in self_record.self_knowledge["cares"])

    entries = store.all_entries()
    kinds = [e.kind for e in entries]
    assert kinds[0] == "self-aware"
    assert "seed" in kinds
    seed_texts = [e.text for e in entries if e.kind == "seed"]
    assert any("Gullmouth harbor" in t for t in seed_texts)


def test_birth_renders_shared_pasts_in_the_first_person(
    tmp_path: Path, examples: Path, clock: Clock
) -> None:
    home = tmp_path / "home"
    path = examples / "pellam-quist.persona.yaml"
    known_names = {IVO_ID: "Ivo Marrowfield"}
    store = birth.birth_synthetic(
        PELLAM_ID, path, home=home, clock=clock, known_public_names=known_names
    )
    texts = [e.text for e in store.all_entries() if e.kind == "seed"]
    regatta = next(t for t in texts if "regatta" in t)
    assert regatta.startswith("I and Ivo Marrowfield crewed")


def test_an_unknown_participant_is_someone_i_once_knew(
    tmp_path: Path, examples: Path, clock: Clock
) -> None:
    home = tmp_path / "home"
    path = examples / "pellam-quist.persona.yaml"
    store = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)
    texts = [e.text for e in store.all_entries() if e.kind == "seed"]
    regatta = next(t for t in texts if "regatta" in t)
    assert "someone I once knew" in regatta


def test_second_start_never_reads_the_definition_even_if_it_changed(
    tmp_path: Path, examples: Path, clock: Clock
) -> None:
    home = tmp_path / "home"
    path = tmp_path / "pellam-quist.persona.yaml"
    path.write_text((examples / "pellam-quist.persona.yaml").read_text(encoding="utf-8"))
    birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)

    path.write_text("not valid yaml at all: [", encoding="utf-8")
    store = birth.birth_synthetic(PELLAM_ID, path, home=home, clock=clock)
    assert store.read_self().public_name == "Pellam Quist"


def test_synthetic_as_resident_is_refused(tmp_path: Path, examples: Path) -> None:
    from sonavida.ports import vault

    with pytest.raises(DefinitionRefused) as excinfo:
        vault.load_resident(examples / "pellam-quist.persona.yaml", tmp_path)
    assert excinfo.value.reason == "synthetic_as_resident"


def test_resident_outside_the_vault_is_refused(tmp_path: Path, examples: Path) -> None:
    from sonavida.ports import vault

    outside = make_scratch_vault(tmp_path / "vault", examples, resident=True)
    somewhere_else = tmp_path / "elsewhere" / "definition.persona.yaml"
    as_resident(examples / "pellam-quist.persona.yaml", somewhere_else)
    with pytest.raises(DefinitionRefused) as excinfo:
        vault.load_resident(somewhere_else, outside)
    assert excinfo.value.reason == "outside_vault"


def test_not_born_without_a_ledger_entry_is_refused(tmp_path: Path, examples: Path) -> None:
    from sonavida.ports import vault

    root = make_scratch_vault(tmp_path / "vault", examples, resident=True)
    path = root / "personas/pellam/definition.persona.yaml"
    with pytest.raises(DefinitionRefused) as excinfo:
        vault.load_resident(path, root)
    assert excinfo.value.reason == "not_born"


def test_changed_since_birth_is_refused(tmp_path: Path, examples: Path) -> None:
    from miraveja_persona.vault import freeze

    from sonavida.ports import vault

    root = make_scratch_vault(tmp_path / "vault", examples, resident=True)
    path = root / "personas/pellam/definition.persona.yaml"
    ok, message = freeze(path, root)
    assert ok, message
    path.write_text(path.read_text(encoding="utf-8") + "\n# a later edit\n", encoding="utf-8")
    with pytest.raises(DefinitionRefused) as excinfo:
        vault.load_resident(path, root)
    assert excinfo.value.reason == "changed_since_birth"


def test_author_note_is_refused(tmp_path: Path, examples: Path) -> None:
    from sonavida.ports import vault

    root = make_scratch_vault(tmp_path / "vault", examples, resident=True)
    note = root / "notes/lighthouse-mural.note.yaml"
    with pytest.raises(DefinitionRefused) as excinfo:
        vault.load_resident(note, root)
    assert excinfo.value.reason == "author_note"


def test_a_resident_birth_via_the_ledger_works_end_to_end(
    tmp_path: Path, examples: Path, clock: Clock
) -> None:
    from miraveja_persona.vault import freeze

    root = make_scratch_vault(tmp_path / "vault", examples, resident=True)
    path = root / "personas/pellam/definition.persona.yaml"
    ok, message = freeze(path, root)
    assert ok, message
    home = tmp_path / "home"
    store = birth.birth_resident(PELLAM_ID, path, root, home=home, clock=clock)
    assert store.read_self().public_name == "Pellam Quist"
