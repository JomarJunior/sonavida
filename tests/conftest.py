"""Shared test fixtures. Every persona fixture here is synthetic (FR-037)."""

from __future__ import annotations

import os
import shutil
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from miraveja_studiolink.client.client import StudioLinkClient
from miraveja_studiolink.standin.app import create_app
from miraveja_studiolink.standin.state import StandInState

from sonavida.ports.studiolink import RealStudioLink, StudioLink

HUB_RELATIVE = Path("specs/003-cofrealma-persona-definition/contracts/examples")
STUDIOLINK_CREDENTIAL = "test-credential"
StudioLinkAndState = tuple[StudioLink, StandInState]

PELLAM_ID = "00000000-0000-4000-8000-00000000a001"
IVO_ID = "00000000-0000-4000-8000-00000000a002"


def hub_examples() -> Path:
    """The hub's spec 003 synthetic examples, from MIRAVEJA_HUB_PATH or a sibling checkout."""
    env = os.environ.get("MIRAVEJA_HUB_PATH")
    candidates = [Path(env)] if env else []
    candidates.append(Path(__file__).resolve().parents[3])
    for base in candidates:
        path = base / HUB_RELATIVE
        if path.is_dir():
            return path
    pytest.skip("hub checkout not found; set MIRAVEJA_HUB_PATH")


@pytest.fixture
def examples() -> Path:
    return hub_examples()


def as_resident(source: Path, target: Path) -> Path:
    """Copy a synthetic example to `target`, re-marked as resident. Only ever in tmp_path."""
    text = source.read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace("nature: synthetic", "nature: resident"), encoding="utf-8")
    return target


def make_scratch_vault(root: Path, examples_dir: Path, *, resident: bool = False) -> Path:
    """A scratch vault holding the two hub example personas and their shared past."""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".cofrealma").write_text("", encoding="utf-8")
    pairs = {
        "pellam-quist.persona.yaml": root / "personas/pellam/definition.persona.yaml",
        "ivo-marrowfield.persona.yaml": root / "personas/ivo/definition.persona.yaml",
        "lighthouse-mural.note.yaml": root / "notes/lighthouse-mural.note.yaml",
    }
    for name, target in pairs.items():
        if resident:
            as_resident(examples_dir / name, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(examples_dir / name, target)
    return root


@pytest.fixture
def scratch_vault(tmp_path: Path, examples: Path) -> Path:
    return make_scratch_vault(tmp_path / "vault", examples)


@pytest.fixture
def sonavida_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sonavida-home"
    home.mkdir()
    monkeypatch.setenv("SONAVIDA_HOME", str(home))
    return home


@pytest.fixture
async def studiolink_and_state() -> AsyncIterator[StudioLinkAndState]:
    """The Studio Link reference stand-in, in process (`httpx.ASGITransport`)."""
    state = StandInState(STUDIOLINK_CREDENTIAL)
    app = create_app(state)
    transport = httpx.ASGITransport(app=app)
    async with StudioLinkClient(
        "http://standin", STUDIOLINK_CREDENTIAL, transport=transport
    ) as client:
        yield RealStudioLink(client), state


class NetworkUsed(AssertionError):
    pass


def _refuse(*_args: object, **_kwargs: object) -> object:
    raise NetworkUsed("sonavida tests must never open a real socket; use the in-process stand-ins")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every socket is blocked. `httpx.ASGITransport` calls the stand-in in process and
    never opens one, so the Studio Link and ModelMora stand-ins are unaffected."""
    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    yield
