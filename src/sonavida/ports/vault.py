"""The `Vault` port: reading a definition, once, through `miraveja-persona` (R-3, R-4).

A thin re-export, so `birth.py` names its one seam here rather than reaching into
`miraveja_persona` directly, and a later change to that library touches one file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from miraveja_persona import Definition, DefinitionRefused
from miraveja_persona import load_resident as _load_resident
from miraveja_persona import load_synthetic as _load_synthetic
from miraveja_persona.pasts import list_pasts as _list_pasts
from miraveja_persona.vault import read_ledger as _read_ledger

__all__ = [
    "Definition",
    "DefinitionRefused",
    "list_pasts",
    "load_resident",
    "load_synthetic",
    "read_ledger",
]


def load_resident(path: Path, cofrealma_root: Path) -> Definition:
    return _load_resident(path, cofrealma_root)


def load_synthetic(path: Path) -> Definition:
    return _load_synthetic(path)


def list_pasts(root: Path) -> list[dict[str, Any]]:
    return _list_pasts(root)


def read_ledger(root: Path) -> list[dict[str, Any]]:
    """Every persona the vault has frozen: `id`, `publicName`, `definition`, `bornOn`."""
    return _read_ledger(root)
