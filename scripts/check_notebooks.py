"""Fail if any notebook has cell outputs or execution counts.

Invoked by `pixi run check-notebooks` as a lint gate. Notebook outputs
should never be committed: they bloat diffs, leak data, and make
code review harder. Run `pixi run clean-notebooks` to strip outputs
in place before committing.
"""

from __future__ import annotations

import pathlib
import sys

import nbformat


def main() -> int:
    leaks = []
    for p in pathlib.Path("notebooks").glob("*.ipynb"):
        nb = nbformat.read(p, as_version=4)
        for cell in nb.cells:
            if cell.get("cell_type") == "code" and (
                cell.get("outputs") or cell.get("execution_count")
            ):
                leaks.append(str(p))
                break
    if leaks:
        print("Notebooks with committed outputs or execution counts:")
        for p in leaks:
            print(f"  {p}")
        print("Run: pixi run clean-notebooks")
        return 1
    print("Notebooks clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
