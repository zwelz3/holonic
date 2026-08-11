#!/usr/bin/env python3
"""Execute every example notebook in a real IPython kernel and fail on errors.

This runs each notebook through ``nbclient`` — the same execution path
Jupyter uses — so cells behave exactly as they do in the UI: top-level
``await``, ``%magic`` lines, rich display, and cell-to-cell state all work
natively. There is deliberately **no source-level heuristic**: a notebook
that is not actually executed is never reported as passing. (The previous
implementation string-matched ``"await "`` and skipped the whole notebook
as OK, and swallowed every ``ImportError`` as OK — both produced false
greens that hid broken examples.)

Statuses reported per notebook:

- ``OK``   — every cell executed without error.
- ``SKIP`` — a cell failed *solely* because an OPTIONAL dependency (one of
  holonic's ``[viz]`` / ``[entailment]`` / ``[fuseki]`` extras) is not
  installed. Distinct from OK so it is visible; does not fail the run, so
  partial-dependency environments stay usable.
- ``FAIL`` — any other error, including a missing *required* dependency.

The process exits non-zero if and only if at least one notebook FAILs.
In CI, install the full extras so nothing is skipped and every cell runs.

Usage (standalone)::

    python scripts/test_notebooks.py

Usage (pixi)::

    pixi run test-notebooks
"""

from __future__ import annotations

import glob
import io
import os
import sys
import textwrap

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

# Modules that are genuinely optional (declared under holonic's [viz],
# [entailment], and [fuseki] extras, plus common notebook-only plotting).
# A cell failing *only* because one of these is absent is a SKIP, not a
# FAIL. A missing REQUIRED dependency (rdflib, pyshacl, ...) is NOT in this
# set, so it surfaces as a real failure.
OPTIONAL_DEPS = frozenset(
    {
        "yfiles_jupyter_graphs",
        "ipywidgets",
        "ipydatagrid",
        "networkx",
        "matplotlib",
        "owlrl",
        "aiohttp",
    }
)

KERNEL_NAME = "python3"
CELL_TIMEOUT = 120  # seconds per cell


def _missing_optional_dep(ename: str, evalue: str) -> str | None:
    """Return the optional module name if the error is its absence, else None.

    Only ``ModuleNotFoundError`` / ``ImportError`` for a module listed in
    ``OPTIONAL_DEPS`` counts. Everything else returns None (a real failure).
    """
    if ename not in ("ModuleNotFoundError", "ImportError"):
        return None
    text = evalue or ""
    for dep in OPTIONAL_DEPS:
        # evalue looks like: No module named 'yfiles_jupyter_graphs'
        if f"'{dep}'" in text or f" {dep}" in text:
            return dep
    return None


def run_notebook(path: str) -> tuple[str, str]:
    """Execute all cells of a notebook in a kernel.

    Returns ``(status, message)`` where status is ``"OK"``, ``"SKIP"``,
    or ``"FAIL"``.
    """
    nb = nbformat.read(path, as_version=4)
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    if not code_cells:
        return "OK", "no code cells"

    client = NotebookClient(
        nb,
        timeout=CELL_TIMEOUT,
        kernel_name=KERNEL_NAME,
        allow_errors=False,
        record_timing=False,
    )
    try:
        client.execute()
    except CellExecutionError as exc:
        dep = _missing_optional_dep(exc.ename, exc.evalue)
        if dep is not None:
            return "SKIP", f"optional dependency {dep!r} not installed"
        # Surface the actual error name/value and the tail of the traceback.
        tail = "\n".join(str(exc).strip().split("\n")[-8:])
        return "FAIL", tail
    except Exception as exc:  # noqa: BLE001 — kernel start/protocol failure
        return "FAIL", f"{type(exc).__name__}: {exc}"

    return "OK", f"{len(code_cells)} cells executed"


def main() -> int:
    """Run every example notebook; return 1 if any FAILed, else 0."""
    # Force UTF-8 output on Windows (cp1252 can't encode the box-drawing
    # and symbol characters used in viz formatters and repr methods).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    elif os.name == "nt":
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )

    paths = sorted(glob.glob("notebooks/[0-9]*.ipynb"))
    if not paths:
        print("No notebooks found in notebooks/")
        return 1

    failures: list[tuple[str, str]] = []
    skips: list[tuple[str, str]] = []
    for path in paths:
        status, msg = run_notebook(path)
        print(f"  {status}: {path} ({msg})")
        if status == "FAIL":
            failures.append((path, msg))
        elif status == "SKIP":
            skips.append((path, msg))

    print()
    if skips:
        print(f"{len(skips)} notebook(s) SKIPPED (optional deps missing):")
        for path, msg in skips:
            print(f"  {path}: {msg}")
        print()
    if failures:
        print(f"{len(failures)} notebook(s) FAILED:")
        for path, msg in failures:
            print(f"  {path}:")
            print(textwrap.indent(msg, "    "))
        return 1

    executed = len(paths) - len(skips)
    tail = f", {len(skips)} skipped." if skips else "."
    print(f"All {executed} executed notebook(s) passed{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
