"""T030: the only code that calls `StudioLink.hand_over_candidate` is the AiGate
stand-in (FR-018, FR-021). A static check over the source, not a run."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "sonavida"


def _files_calling(attribute: str) -> list[Path]:
    hits = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == attribute:
                hits.append(path)
                break
    return hits


def test_only_the_gate_standin_calls_hand_over_candidate() -> None:
    callers = _files_calling("hand_over_candidate")
    relative = {p.relative_to(SRC) for p in callers}
    assert relative <= {
        Path("standins/gate.py"),
        Path("ports/studiolink.py"),  # the port's own definition and adapter method
    }
    assert Path("standins/gate.py") in relative


def test_nothing_from_self_knowledge_or_memory_is_passed_to_the_gate() -> None:
    """The gate's `submit` signature (ports/gate.py) carries only a piece's public
    face: identifiers, title, statement, image, description and suggested labels —
    never `self`, an intention, memory or reasoning."""
    text = (SRC / "ports" / "gate.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    (submit_def,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "submit"
    ]
    arg_names = {a.arg for a in submit_def.args.kwonlyargs}
    forbidden = {"self_knowledge", "self", "memory", "reasoning", "intention", "definition"}
    assert not (arg_names & forbidden)
    assert arg_names == {
        "persona_id",
        "public_name",
        "piece_id",
        "title",
        "statement",
        "image_bytes",
        "neutral_description",
        "suggested_labels",
    }
