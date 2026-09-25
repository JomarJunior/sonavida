"""T047: a marker phrase in every prose field of a synthetic persona never reaches a
log line, the CLI's own stdout or stderr, or any file outside `$SONAVIDA_HOME`
(FR-034, SC-008)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sonavida import birth
from sonavida.ports.clock import SimulatedClock
from sonavida.runtime import Runtime
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.models import ScriptedModels
from sonavida.standins.perception import ScriptedPerception

from ..conftest import StudioLinkAndState

MARKER = "zzmarker-9f3ba2c7-privacy-canary"
CANARY_ID = "00000000-0000-4000-8000-00000000a088"

CANARY_DEFINITION = f"""\
miravejaPersona: 1
nature: synthetic

identity:
  id: {CANARY_ID}
  publicName: Canary Test Persona
  about: |
    {MARKER} about.
  openlyAI: true
  selfUnderstanding: |
    {MARKER} self-understanding.

taste:
  drawnTo: |
    {MARKER} drawn-to.
  themes:
    - "{MARKER} theme"
  stylesAndMedia: |
    {MARKER} styles-and-media.
  dislikes: |
    {MARKER} dislikes.

voice:
  speech: |
    {MARKER} speech.
  temperament: |
    {MARKER} temperament.

tendencies:
  presence: |
    {MARKER} presence-tendency.
  work: |
    {MARKER} work-tendency.

cares:
  - "{MARKER} cares"

craft: |
  {MARKER} craft.

selfImage: |
  {MARKER} self-image.

lore:
  names:
    - name: {MARKER}-place
      is: place

seedMemories:
  - id: canary-seed
    when: as a young persona
    happened: |
      {MARKER} seed memory.
"""


@pytest.fixture
def canary_path(tmp_path: Path) -> Path:
    path = tmp_path / "canary.persona.yaml"
    path.write_text(CANARY_DEFINITION, encoding="utf-8")
    return path


async def test_a_simulated_week_writes_the_marker_to_no_log_line(
    tmp_path: Path,
    canary_path: Path,
    studiolink_and_state: StudioLinkAndState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    clock = SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=5)
    store = birth.birth_synthetic(CANARY_ID, canary_path, home=home, clock=clock)

    runtime = Runtime(
        home=home,
        clock=clock,
        models=ScriptedModels(),
        studiolink=studiolink,
        perception=ScriptedPerception(),
        gate=ScriptedGate(studiolink),
    )
    runtime.host(store, CANARY_ID)

    with caplog.at_level(logging.DEBUG):
        clock.join()
        await clock.wait_until(clock.now() + timedelta(days=7))
        clock.leave()
        await runtime.shutdown()

    for record in caplog.records:
        assert MARKER not in record.getMessage(), (
            f"marker leaked into a log record: {record.getMessage()!r}"
        )


def _env(home: Path, tmp_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["SONAVIDA_HOME"] = str(home)
    env["TMPDIR"] = str(tmp_root)
    return env


def test_a_simulated_week_writes_the_marker_to_no_cli_output_or_file_outside_home(
    tmp_path: Path, canary_path: Path
) -> None:
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    vault.mkdir()
    vault_path = vault / "canary.persona.yaml"
    vault_path.write_text(canary_path.read_text(encoding="utf-8"), encoding="utf-8")

    pre_existing = {p for p in tmp_path.rglob("*") if p.is_file()}

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sonavida.cli",
            "run",
            "--vault",
            str(vault),
            "--simulate",
            "7",
            "--seed",
            "5",
            "--standins",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=_env(home, tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert MARKER not in result.stdout
    assert MARKER not in result.stderr

    for path in tmp_path.rglob("*"):
        if not path.is_file() or path in pre_existing:
            continue
        try:
            home.resolve()
            path.resolve().relative_to(home.resolve())
        except ValueError:
            pass
        else:
            continue  # inside $SONAVIDA_HOME: the persona's own memory, allowed
        marker_bytes = MARKER.encode("utf-8")
        assert marker_bytes not in path.read_bytes(), (
            f"marker leaked into a file outside home: {path}"
        )
