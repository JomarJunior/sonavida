"""`sonavida` command line (contracts/cli.md)."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import yaml
from miraveja_studiolink.client.client import StudioLinkClient
from miraveja_studiolink.standin.app import create_app
from miraveja_studiolink.standin.state import StandInState

from sonavida import birth
from sonavida.memory import reader
from sonavida.memory.store import MemoryStore
from sonavida.ports import vault
from sonavida.ports.clock import RealClock, SimulatedClock
from sonavida.ports.models import ModelMoraClient
from sonavida.ports.studiolink import RealStudioLink
from sonavida.ports.vault import DefinitionRefused
from sonavida.runtime import AlreadyAlive, Departed, Runtime
from sonavida.standins.gate import ScriptedGate
from sonavida.standins.models import ScriptedModels
from sonavida.standins.perception import ModelsPerception, ScriptedPerception


def _home() -> Path:
    raw = os.environ.get("SONAVIDA_HOME")
    if not raw:
        print("refused: SONAVIDA_HOME is not set", file=sys.stderr)
        raise SystemExit(2)
    home = Path(raw)
    home.mkdir(parents=True, exist_ok=True)
    return home


def _peek_synthetic_id(path: Path) -> str | None:
    """Only the identifier, to enumerate scratch synthetic vaults for `--simulate`.

    Not "reading the definition" in the FR-002 sense: no prose leaves this function.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    identity = data.get("identity")
    if not isinstance(identity, dict):
        return None
    persona_id = identity.get("id")
    return persona_id if isinstance(persona_id, str) else None


def _discover_synthetic(vault_root: Path, only: Sequence[str] | None) -> list[tuple[str, Path]]:
    found = []
    for path in sorted(vault_root.rglob("*.persona.yaml")):
        if only and path.stem.removesuffix(".persona") not in only:
            continue
        persona_id = _peek_synthetic_id(path)
        if persona_id is not None:
            found.append((persona_id, path))
    return found


async def _run_simulated(
    home: Path, *, vault_root: Path | None, only: Sequence[str] | None, days: int, seed: int
) -> int:
    clock = SimulatedClock(start=datetime(2026, 1, 1, tzinfo=UTC), seed=seed)
    models = ScriptedModels()
    perception = ScriptedPerception()
    state = StandInState("sonavida-cli-standin")
    app = create_app(state)
    transport = httpx.ASGITransport(app=app)
    credential = "sonavida-cli-standin"
    async with StudioLinkClient("http://standin", credential, transport=transport) as client:
        studiolink = RealStudioLink(client)
        gate = ScriptedGate(studiolink, is_reference_standin=True)
        runtime = Runtime(
            home=home,
            clock=clock,
            models=models,
            studiolink=studiolink,
            perception=perception,
            gate=gate,
        )
        hosted = 0
        if vault_root is not None:
            for persona_id, path in _discover_synthetic(vault_root, only):
                try:
                    store = birth.birth_synthetic(persona_id, path, home=home, clock=clock)
                except DefinitionRefused as refused:
                    print(f"refused: {refused.reason}", file=sys.stderr)
                    return 1
                try:
                    runtime.host(store, persona_id)
                except AlreadyAlive:
                    print(f"refused: already_alive: {persona_id}", file=sys.stderr)
                    return 1
                except Departed:
                    print(f"refused: departed: {persona_id}", file=sys.stderr)
                    return 1
                hosted += 1
        if hosted == 0:
            print("no personas to bring to life", file=sys.stderr)

        driver_target = clock.now() + timedelta(days=days)
        clock.join()
        signalled = asyncio.get_running_loop().create_future()
        _install_signal_handlers(signalled)
        try:
            _done, pending = await asyncio.wait(
                {asyncio.ensure_future(clock.wait_until(driver_target)), signalled},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
        finally:
            clock.leave()
        # FR-008: on SIGINT/SIGTERM as much as on reaching the end of the simulated
        # run, every living persona is announced as away, in order, before stopping.
        await runtime.shutdown()
    return 0


def _install_signal_handlers(signalled: asyncio.Future[None]) -> None:
    loop = asyncio.get_running_loop()

    def _handle(*_args: object) -> None:
        if not signalled.done():
            signalled.set_result(None)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle)
        except NotImplementedError:  # pragma: no cover - platforms without signal support
            signal.signal(sig, _handle)


async def _run_dry_run(home: Path, *, vault_root: Path, only: Sequence[str] | None) -> int:
    """Pre-alpha, on the Studio: real **🧠 ModelMora** and real clock, but no path can
    ever reach a real Museum side (Principle III, R-9, contracts/cli.md)."""
    clock = RealClock()
    modelmora_url = os.environ.get("MODELMORA_URL", "http://127.0.0.1:8431")
    modelmora_token = os.environ.get("MODELMORA_TOKEN", "")
    models = ModelMoraClient(modelmora_url, modelmora_token)
    perception = ModelsPerception(models)
    state = StandInState("sonavida-cli-standin")
    app = create_app(state)
    transport = httpx.ASGITransport(app=app)
    credential = "sonavida-cli-standin"
    try:
        async with StudioLinkClient("http://standin", credential, transport=transport) as client:
            studiolink = RealStudioLink(client)
            gate = ScriptedGate(studiolink, is_reference_standin=True)
            runtime = Runtime(
                home=home,
                clock=clock,
                models=models,
                studiolink=studiolink,
                perception=perception,
                gate=gate,
            )
            for entry in vault.read_ledger(vault_root):
                persona_id = str(entry["id"])
                definition_relative = str(entry["definition"])
                slug = Path(definition_relative).stem.removesuffix(".persona")
                if only and slug not in only:
                    continue
                definition_path = vault_root / definition_relative
                try:
                    store = birth.birth_resident(
                        persona_id, definition_path, vault_root, home=home, clock=clock
                    )
                except DefinitionRefused as refused:
                    print(f"refused: {refused.reason}", file=sys.stderr)
                    return 1
                try:
                    runtime.host(store, persona_id)
                except AlreadyAlive:
                    print(f"refused: already_alive: {persona_id}", file=sys.stderr)
                    return 1
                except Departed:
                    print(f"refused: departed: {persona_id}", file=sys.stderr)
                    return 1

            signalled: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            _install_signal_handlers(signalled)
            await signalled
            await runtime.shutdown()
    finally:
        await models.aclose()
    return 0


async def _run_real() -> int:
    # No real AI gate exists yet (roadmap 006 / T031): a real Museum side must never
    # receive a piece with a verdict that never judged the hard lines (Principle III,
    # R-9). Real `run` refuses until a real gate is wired in.
    print("refused: gate_not_configured", file=sys.stderr)
    return 1


def cmd_run(args: argparse.Namespace) -> int:
    home = _home()
    if args.simulate is not None:
        if not args.standins:
            print("refused: --simulate requires --standins", file=sys.stderr)
            return 2
        return asyncio.run(
            _run_simulated(
                home,
                vault_root=args.vault,
                only=args.persona,
                days=args.simulate,
                seed=args.seed if args.seed is not None else 0,
            )
        )
    if args.vault is None:
        print("refused: --vault is required outside --simulate", file=sys.stderr)
        return 2
    if args.dry_run:
        return asyncio.run(_run_dry_run(home, vault_root=args.vault, only=args.persona))
    return asyncio.run(_run_real())


def cmd_status(args: argparse.Namespace) -> int:
    home = _home()
    personas_dir = home / "personas"
    if not personas_dir.is_dir():
        return 0
    for persona_dir in sorted(personas_dir.iterdir()):
        memory_path = persona_dir / "memory.sqlite"
        if not memory_path.is_file():
            continue
        with MemoryStore(memory_path, mode="ro") as store:
            self_record = store.read_self()
            if self_record.departed_at is not None:
                print(f"{self_record.public_name}: departed")
                continue
            presence = "away"
            for entry in reversed(store.all_entries()):
                if entry.kind == "presence":
                    presence = entry.text
                    break
            print(f"{self_record.public_name}: {presence}")
    return 0


def _resolve_persona_memory_path(home: Path, persona: str) -> Path | None:
    """`persona` may be the persona id (the directory name) or its public name."""
    direct = birth.persona_memory_path(home, persona)
    if direct.is_file():
        return direct
    personas_dir = home / "personas"
    if not personas_dir.is_dir():
        return None
    for persona_dir in sorted(personas_dir.iterdir()):
        memory_path = persona_dir / "memory.sqlite"
        if not memory_path.is_file():
            continue
        with MemoryStore(memory_path, mode="ro") as store:
            if store.read_self().public_name == persona:
                return memory_path
    return None


def cmd_memory(args: argparse.Namespace) -> int:
    home = _home()
    path = _resolve_persona_memory_path(home, args.persona)
    if path is None:
        print(f"refused: no such persona: {args.persona}", file=sys.stderr)
        return 2
    since = date.fromisoformat(args.from_date) if args.from_date else None
    until = date.fromisoformat(args.to_date) if args.to_date else None
    for entry in reader.read_memory(path, since=since, until=until):
        print(entry.line)
    return 0


def cmd_pieces(args: argparse.Namespace) -> int:
    home = _home()
    path = _resolve_persona_memory_path(home, args.persona)
    if path is None:
        print(f"refused: no such persona: {args.persona}", file=sys.stderr)
        return 2
    for line in reader.read_pieces(path):
        print(line)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sonavida")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--vault", type=Path, default=None)
    run.add_argument("--persona", action="append", default=None)
    run.add_argument("--simulate", type=int, default=None, metavar="DAYS")
    run.add_argument("--seed", type=int, default=None)
    run.add_argument("--standins", action="store_true")
    run.add_argument("--dry-run", action="store_true", dest="dry_run")
    run.set_defaults(func=cmd_run)

    memory = sub.add_parser("memory")
    memory.add_argument("persona")
    memory.add_argument("--from", dest="from_date", default=None)
    memory.add_argument("--to", dest="to_date", default=None)
    memory.set_defaults(func=cmd_memory)

    pieces = sub.add_parser("pieces")
    pieces.add_argument("persona")
    pieces.set_defaults(func=cmd_pieces)

    status = sub.add_parser("status")
    status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
