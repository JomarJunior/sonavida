"""T030a: no bypass around the AI gate (Principle III, R-9).

`sonavida run` without `--simulate --standins` and without a real AI gate configured
refuses to start with `gate_not_configured`; the gate stand-in refuses to hand a
candidate to any Studio Link target other than the in-process reference stand-in.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from sonavida.ports.gate import Verdict
from sonavida.standins.gate import GateBypassRefused, ScriptedGate

from ..conftest import make_scratch_vault
from .conftest import StudioLinkAndState


def test_run_without_simulate_standins_refuses_gate_not_configured(
    tmp_path: Path, examples: Path
) -> None:
    home = tmp_path / "home"
    vault = make_scratch_vault(tmp_path / "vault", examples, resident=True)
    env = dict(os.environ)
    env["SONAVIDA_HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, "-m", "sonavida.cli", "run", "--vault", str(vault)],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    assert "gate_not_configured" in result.stderr


class _FakeNonReferenceStudioLink:
    """Shaped like a `StudioLink` that is NOT the in-process reference stand-in."""

    async def hand_over_candidate(self, **_kwargs: object) -> None:
        raise AssertionError("must never be called: the gate refuses before this point")


async def test_gate_standin_refuses_any_non_reference_studiolink_target() -> None:
    gate = ScriptedGate(_FakeNonReferenceStudioLink(), is_reference_standin=False)  # type: ignore[arg-type]
    gate.script(Verdict(accepted=True, reason="would be accepted", labels=frozenset()))
    with pytest.raises(GateBypassRefused):
        await gate.submit(
            persona_id=uuid.UUID("00000000-0000-4000-8000-00000000a001"),
            public_name="Pellam Quist",
            piece_id=uuid.uuid4(),
            title="Harbor",
            statement="A quiet harbor.",
            image_bytes=b"\x89PNG\r\n",
            neutral_description="a harbor scene.",
            suggested_labels=frozenset(),
        )


async def test_gate_standin_bound_to_the_reference_standin_hands_over_normally(
    studiolink_and_state: StudioLinkAndState,
) -> None:
    studiolink, state = studiolink_and_state
    gate = ScriptedGate(studiolink, is_reference_standin=True)
    gate.script(Verdict(accepted=True, reason="fits.", labels=frozenset()))
    piece_id = uuid.uuid4()
    await gate.submit(
        persona_id=uuid.UUID("00000000-0000-4000-8000-00000000a001"),
        public_name="Pellam Quist",
        piece_id=piece_id,
        title="Harbor",
        statement="A quiet harbor.",
        image_bytes=b"\x89PNG\r\n\x1a\n\x00\x00",
        neutral_description="a harbor scene.",
        suggested_labels=frozenset(),
    )
    assert piece_id in state.pieces
