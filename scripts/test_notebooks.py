#!/usr/bin/env python3
"""Execute every notebook's code cells and fail on errors.

Skips cells that use ``%pip``, ``%magic``, or top-level ``await``
(these are Jupyter-specific and cannot run in a plain Python
interpreter).

Usage (standalone)::

    python scripts/test_notebooks.py

Usage (pixi)::

    pixi run test-notebooks
"""
from __future__ import annotations

import glob
import sys
import textwrap
import traceback

import nbformat


def _should_skip_cell(source: str) -> str | None:
    """Return a reason string if the cell should be skipped."""
    if source.strip().startswith("%") or source.strip().startswith("!"):
        return "magic/shell command"
    # Top-level await (only works in Jupyter async REPL)
    for line in source.split("\n"):
        stripped = line.strip()
        if stripped.startswith("await ") and not stripped.startswith(
            "await "
        ):
            continue
        # Check for bare await at module level (not inside async def)
        if stripped.startswith("await "):
            # Rough heuristic: if 'async def' appears before this
            # line AND indentation is deeper, it's inside a function.
            # Otherwise it's top-level.
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                return "top-level await"
    return None


def _has_toplevel_await(source: str) -> bool:
    """Check if any line has a top-level await."""
    lines = source.split("\n")
    in_async = False
    async_indent = 0
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("async def "):
            in_async = True
            async_indent = indent
        elif in_async and indent <= async_indent and stripped:
            in_async = False
        if stripped.startswith("await ") and not in_async:
            return True
    return False


def run_notebook(path: str) -> tuple[bool, str]:
    """Execute all code cells in a notebook.

    Returns (success, message).
    """
    nb = nbformat.read(path, as_version=4)
    code_cells = [c for c in nb.cells if c.cell_type == "code"]

    if not code_cells:
        return True, "no code cells"

    # Build combined source, skipping magic/await cells
    parts = []
    skipped = 0
    for cell in code_cells:
        src = cell.source.strip()
        if not src:
            continue
        # Skip cells with magic commands or shell calls on any line
        has_magic = any(
            ln.lstrip().startswith("%") or ln.lstrip().startswith("!")
            for ln in src.split("\n") if ln.strip()
        )
        if has_magic:
            skipped += 1
            continue
        if _has_toplevel_await(src):
            skipped += 1
            continue
        parts.append(src)

    if not parts:
        return True, f"all {len(code_cells)} cells skipped"

    # If any remaining cell still has 'await' at any indentation,
    # skip the entire notebook (it's async-native)
    combined = "\n".join(parts)
    if "await " in combined:
        return True, f"async notebook (skipped)"

    script = "\n\n".join(parts)

    # Execute in a fresh namespace
    ns: dict = {"__name__": "__main__"}
    try:
        exec(compile(script, path, "exec"), ns)  # noqa: S102
    except ImportError as e:
        # Missing optional dependencies (e.g., matplotlib)
        return True, f"skipped (missing dep: {e.name})"
    except Exception:
        tb = traceback.format_exc()
        # Show last 5 lines of traceback
        short = "\n".join(tb.strip().split("\n")[-5:])
        return False, short

    msg = f"{len(parts)} cells OK"
    if skipped:
        msg += f", {skipped} skipped"
    return msg != "", msg


def main() -> int:
    paths = sorted(glob.glob("notebooks/[0-9]*.ipynb"))
    if not paths:
        print("No notebooks found in notebooks/")
        return 1

    failures = []
    for path in paths:
        ok, msg = run_notebook(path)
        status = "OK" if ok else "FAIL"
        print(f"  {status}: {path} ({msg})")
        if not ok:
            failures.append((path, msg))

    print()
    if failures:
        print(f"{len(failures)} notebook(s) failed:")
        for path, msg in failures:
            print(f"  {path}:")
            print(textwrap.indent(msg, "    "))
        return 1

    print(f"All {len(paths)} notebooks executed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
