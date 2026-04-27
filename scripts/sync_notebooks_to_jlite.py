"""Copy example notebooks from notebooks/ into jupyterlite/content/.

Keeps the two directories in sync so the next `pixi run build_jl`
picks up any changes. The landing notebook (00_start_here.ipynb) is
preserved because it only exists in jupyterlite/content/ and is
JupyterLite-specific content.
"""

from __future__ import annotations

import pathlib
import shutil
import sys


def main() -> int:
    source = pathlib.Path("notebooks")
    target = pathlib.Path("jupyterlite/content")

    if not source.is_dir():
        print(f"error: {source} not found; run from repo root", file=sys.stderr)
        return 1

    target.mkdir(parents=True, exist_ok=True)

    copied = 0
    for nb in sorted(source.glob("*.ipynb")):
        # Skip landing pages — each directory has its own
        if nb.name.startswith("00_"):
            continue
        shutil.copy2(nb, target / nb.name)
        copied += 1
        print(f"  {nb.name}")

    print(f"Copied {copied} notebooks from {source}/ to {target}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
