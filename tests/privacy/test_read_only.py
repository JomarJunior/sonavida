"""T039: `memory` and `pieces` open the file `mode=ro`; nothing writes to memory from
here; there is no network listener anywhere in the package (FR-035, FR-036)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonavida import cli
from sonavida.memory import reader
from sonavida.memory.store import MemoryStore

SRC = Path(__file__).resolve().parents[2] / "src" / "sonavida"

# A network *listener* binds or accepts; a client connecting out (to ModelMora, or to
# the Museum side through the Studio Link) is not one, and neither is running the
# Studio Link reference stand-in in process over `httpx.ASGITransport` for tests and
# `--simulate`/`--dry-run` — no socket is ever opened for either.
LISTENER_CALLS = ("bind(", "listen(", "start_server(", "uvicorn.run(", ".serve(")


def test_no_network_listener_anywhere_in_the_package() -> None:
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for call in LISTENER_CALLS:
            assert call not in text, f"{path}: found {call!r}, a possible network listener"


def test_reader_module_only_ever_opens_memory_read_only() -> None:
    tree = ast.parse((SRC / "memory" / "reader.py").read_text(encoding="utf-8"))
    write_methods = {
        "append",
        "write_self",
        "record_departure",
        "create_piece",
        "update_piece",
        "add_attempt",
        "update_attempt",
        "set_experiences_acknowledged_through",
        "set_erasures_acknowledged_through",
    }
    # only calls made on the `store` variable itself; `list.append` shares a name
    # with `MemoryStore.append` but is not it.
    called_on_store = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "store"
    }
    assert not (called_on_store & write_methods)

    # every `MemoryStore(...)` construction in this module passes mode="ro".
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "MemoryStore"
        ):
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            assert "mode" in kwargs
            assert isinstance(kwargs["mode"], ast.Constant)
            assert kwargs["mode"].value == "ro"


def test_memory_and_pieces_commands_work_against_a_file_made_read_only_on_disk(
    tmp_path: Path,
) -> None:
    path = tmp_path / "memory.sqlite"
    store = MemoryStore(path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.write_self(persona_id="p1", public_name="Pellam Quist", self_knowledge={}, born_at=now)
    store.append(at=now, kind="chose-nothing", text="chose to do nothing.", importance=1)
    store.close()
    path.chmod(0o444)

    # a read-write open of this file would fail; reading must not attempt one.
    lines = [entry.line for entry in reader.read_memory(path)]
    assert lines
    assert reader.read_pieces(path) == []


def test_no_cli_command_writes_to_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("SONAVIDA_HOME", str(home))
    persona_dir = home / "personas" / "p1"
    persona_dir.mkdir(parents=True)
    path = persona_dir / "memory.sqlite"
    store = MemoryStore(path)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.write_self(persona_id="p1", public_name="Pellam Quist", self_knowledge={}, born_at=now)
    store.close()
    path.chmod(0o444)

    assert cli.main(["memory", "p1"]) == 0
    assert cli.main(["pieces", "p1"]) == 0
    assert cli.main(["status"]) == 0
