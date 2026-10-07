"""Guard: no ace-web code reads (or copies) a legacy ask store.

Operator decision (Jonathan Jackson, 2026-10-07): "why do we even have
open-asks.yml? why isn't that just a filter of decisions … when we created
the new system we should not have carried forward any legacy models".

A run's open asks are a FILTER of its own ``decisions.yaml`` rows
(``summary._open_asks``). The opp-level ``open-questions.md`` ledger and the
generated ``open-asks.yaml`` are not read, rendered, cloned or forked by
anything here. This scans every non-test Python module for a string literal
naming either file (docstrings and comments are prose about history and are
allowed), so a reader or a copy list that brings one back fails CI.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
LEGACY_NAMES = ("open-questions.md", "open-asks.yaml", "open-asks.yml")


def _sources() -> list[Path]:
    out = []
    for root in ("apps", "ace_web", "config"):
        base = REPO / root
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            parts = set(path.relative_to(REPO).parts)
            if "tests" in parts or "migrations" in parts or path.name.startswith("test_"):
                continue
            out.append(path)
    return out


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant
            ):
                ids.add(id(body[0].value))
    return ids


def _legacy_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and any(name in node.value for name in LEGACY_NAMES)
        ):
            hits.append(f"{path.relative_to(REPO)}:{node.lineno}: {node.value!r}")
    return hits


def test_the_scan_sees_the_summary_reader():
    """Non-vacuous: the scan covers the module that used to read the ledger."""
    assert REPO / "apps" / "opps" / "summary.py" in _sources()
    assert REPO / "apps" / "opps" / "run_cloner.py" in _sources()


@pytest.mark.parametrize("name", LEGACY_NAMES)
def test_the_scan_would_catch_a_reintroduced_reader(tmp_path, name):
    probe = tmp_path / "probe.py"
    probe.write_text(
        f'"""Docstring mentioning {name} is fine."""\n'
        f'def f(drive, folder):\n    return find(drive, folder, "{name}")\n'
    )
    tree = ast.parse(probe.read_text())
    docstrings = _docstring_nodes(tree)
    found = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in docstrings and name in n.value
    ]
    assert len(found) == 1


def test_no_source_names_a_legacy_ask_store():
    hits = [hit for path in _sources() for hit in _legacy_literals(path)]
    assert hits == [], (
        "A legacy ask store is referenced again. Open asks are a filter of the "
        "run's decisions.yaml (summary._open_asks); do not read, render or copy "
        "open-questions.md / open-asks.yaml:\n" + "\n".join(hits)
    )
