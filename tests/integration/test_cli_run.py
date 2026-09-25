"""T024: `sonavida run --simulate DAYS --seed N --standins` end to end, and SIGTERM (FR-008)."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sonavida.birth import persona_memory_path
from sonavida.memory.store import MemoryStore

from ..conftest import PELLAM_ID, make_scratch_vault


def _env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["SONAVIDA_HOME"] = str(home)
    return env


def test_simulate_run_exits_zero_and_lives_the_synthetic_persona(
    tmp_path: Path, examples: Path
) -> None:
    home = tmp_path / "home"
    vault = make_scratch_vault(tmp_path / "vault", examples)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sonavida.cli",
            "run",
            "--vault",
            str(vault),
            "--simulate",
            "2",
            "--seed",
            "7",
            "--standins",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "refused" not in result.stderr, result.stderr

    store = MemoryStore(persona_memory_path(home, PELLAM_ID), mode="ro")
    entries = store.all_entries()
    assert any(e.kind == "self-aware" for e in entries)


def test_sigterm_announces_every_persona_as_away_before_exiting(
    tmp_path: Path, examples: Path
) -> None:
    home = tmp_path / "home"
    vault = make_scratch_vault(tmp_path / "vault", examples)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sonavida.cli",
            "run",
            "--vault",
            str(vault),
            "--simulate",
            "3650",
            "--seed",
            "3",
            "--standins",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=_env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(1.5)
    process.send_signal(signal.SIGTERM)
    try:
        _out, err = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        raise
    assert process.returncode == 0, err

    for persona_id in (PELLAM_ID, "00000000-0000-4000-8000-00000000a002"):
        memory_path = persona_memory_path(home, persona_id)
        if not memory_path.is_file():
            continue
        store = MemoryStore(memory_path, mode="ro")
        presence_entries = [e for e in store.all_entries() if e.kind == "presence"]
        assert presence_entries, f"{persona_id} never announced presence"
        assert presence_entries[-1].text == "away"


def test_simulate_with_no_personas_says_so(tmp_path: Path) -> None:
    """An empty run is never mistaken for a working one (contracts/cli.md, T056)."""
    home = tmp_path / "home"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sonavida.cli",
            "run",
            "--simulate",
            "1",
            "--seed",
            "1",
            "--standins",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=_env(home),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "no personas to bring to life" in result.stderr


def test_memory_piped_into_a_reader_that_stops_early_exits_quietly(
    tmp_path: Path, examples: Path
) -> None:
    """`sonavida memory PERSONA | head` is how the quickstart reads a life; the reader
    closing the pipe early is not an error."""
    home = tmp_path / "home"
    vault = make_scratch_vault(tmp_path / "vault", examples)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sonavida.cli",
            "run",
            "--vault",
            str(vault),
            "--simulate",
            "2",
            "--seed",
            "7",
            "--standins",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=_env(home),
        check=True,
        capture_output=True,
        timeout=60,
    )
    reader = subprocess.Popen(
        [sys.executable, "-m", "sonavida.cli", "memory", "Pellam Quist"],
        cwd=Path(__file__).resolve().parents[2],
        env=_env(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    assert reader.stdout is not None and reader.stderr is not None
    # Closed before the command can write anything, so its first write meets a closed pipe.
    reader.stdout.close()
    stderr = reader.stderr.read().decode()
    assert reader.wait(timeout=30) == 0, stderr
    assert "Traceback" not in stderr
