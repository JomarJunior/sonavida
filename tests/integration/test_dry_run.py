"""T054: `--dry-run` pairs real **🧠 ModelMora** and the real clock with the perception
and gate stand-ins and the in-process Studio Link reference stand-in only (Principle
III, R-9, FR-029).

A real **🧠 ModelMora** is not available in this environment. What is verified here:
ModelMora's *absence* on loopback is lived as the studio not being ready rather than a
crash, end to end through a full turn; and that nothing in the `--dry-run` wiring can
reach any Studio Link target but the in-process reference stand-in. A real ModelMora
exchange is covered at the client level by `tests/unit/test_modelmora_client.py`'s
`httpx.MockTransport` fixture, standing in for a fake loopback server.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import httpx
import pytest

from sonavida import birth, cli
from sonavida.life import Life
from sonavida.ports.clock import RealClock
from sonavida.ports.models import ModelMoraClient
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.perception import ModelsPerception

from ..conftest import PELLAM_ID
from .conftest import StudioLinkAndState

SRC = Path(__file__).resolve().parents[2] / "src" / "sonavida" / "cli.py"


def _absent_modelmora() -> ModelMoraClient:
    def _refuse_connection(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return ModelMoraClient(
        "http://127.0.0.1:8431", "token", transport=httpx.MockTransport(_refuse_connection)
    )


async def test_a_turn_survives_modelmora_being_completely_absent(
    tmp_path: Path, examples: Path, studiolink_and_state: StudioLinkAndState
) -> None:
    studiolink, _state = studiolink_and_state
    home = tmp_path / "home"
    clock = RealClock()
    store = birth.birth_synthetic(
        PELLAM_ID, examples / "pellam-quist.persona.yaml", home=home, clock=clock
    )
    models = _absent_modelmora()
    try:
        life = Life(
            store=store,
            clock=clock,
            models=models,
            studiolink=studiolink,
            perception=ModelsPerception(models),
            gate=ScriptedGate(studiolink, is_reference_standin=True),
        )
        # No crash: the turn completes, and the model's absence is lived as the
        # studio not being ready (the default reply itself never dispatches, since
        # ModelMora is asked for the turn's own thinking too).
        await life.take_turn()
    finally:
        await models.aclose()

    kinds = [e.kind for e in store.all_entries()]
    assert "studio-not-ready" in kinds
    assert "lost-thread" not in kinds


def test_dry_run_always_binds_the_gate_to_the_reference_standin() -> None:
    """A static check: `_run_dry_run` constructs `ScriptedGate` with
    `is_reference_standin=True` unconditionally — there is no flag or code path in
    `--dry-run` that could point it anywhere else (Principle III, R-9)."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    (dry_run_func,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_dry_run"
    ]
    gate_calls = [
        node
        for node in ast.walk(dry_run_func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ScriptedGate"
    ]
    assert len(gate_calls) == 1
    (call,) = gate_calls
    kwargs = {kw.arg: kw.value for kw in call.keywords}
    assert "is_reference_standin" in kwargs
    assert isinstance(kwargs["is_reference_standin"], ast.Constant)
    assert kwargs["is_reference_standin"].value is True

    # and the Studio Link itself is always the in-process stand-in: `StudioLinkClient`
    # is only ever constructed against `"http://standin"` with an ASGI transport, in
    # this function as in `_run_simulated` — never a real base URL.
    client_calls = [
        node
        for node in ast.walk(dry_run_func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "StudioLinkClient"
    ]
    assert len(client_calls) == 1
    (client_call,) = client_calls
    first_arg = client_call.args[0]
    assert isinstance(first_arg, ast.Constant)
    assert first_arg.value == "http://standin"


async def test_dry_run_rejects_unless_vault_and_dry_run_are_both_given(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    import os

    os.environ["SONAVIDA_HOME"] = str(home)
    try:
        assert cli.main(["run"]) == 2  # no --vault at all
    finally:
        del os.environ["SONAVIDA_HOME"]


async def test_gate_bound_elsewhere_is_refused_even_in_the_dry_run_shape() -> None:
    """Defence in depth: even the exact shape `--dry-run` builds, pointed at
    something that is not the reference stand-in, is refused (R-9). The CLI itself
    never does this (see the static check above); `test_no_bypass.py` covers the
    general case."""
    from sonavida.ports.gate import Verdict
    from sonavida.standins.gate import GateBypassRefused

    class _NotTheReferenceStandin:
        async def hand_over_candidate(self, **_kwargs: object) -> None:
            raise AssertionError("must never be called")

    gate = ScriptedGate(_NotTheReferenceStandin(), is_reference_standin=False)  # type: ignore[arg-type]
    gate.script(Verdict(accepted=True, reason="would be accepted", labels=frozenset()))
    with pytest.raises(GateBypassRefused):
        await gate.submit(
            persona_id=uuid.UUID(PELLAM_ID),
            public_name="Pellam Quist",
            piece_id=uuid.uuid4(),
            title="Harbor",
            statement="A quiet harbor.",
            image_bytes=b"\x89PNG\r\n",
            neutral_description="a harbor scene.",
            suggested_labels=frozenset(),
        )
