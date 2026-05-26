"""Copy example notebooks from notebooks/ into jupyterlite/content/.

Keeps the two directories in sync so the next ``pixi run build_jl``
picks up any changes. The landing notebook (00_start_here.ipynb) is
preserved because it only exists in jupyterlite/content/ and is
JupyterLite-specific content.

Each copied notebook gets a ``%pip install --quiet holonic`` cell
injected at the top so that holonic is available regardless of
which notebook the user opens first.
"""

from __future__ import annotations

import pathlib
import sys

import nbformat


_PIP_CELL_SOURCE = """%pip install --quiet holonic

import holonic
print(f"holonic {holonic.__version__}")
"""


def _has_pip_install(nb: nbformat.NotebookNode) -> bool:
    """Check if the notebook already has a %pip install holonic cell."""
    for cell in nb.cells:
        if cell.cell_type == "code" and _PIP_CELL_SOURCE in cell.source:
            return True
    return False


def main() -> int:
    source = pathlib.Path("notebooks")
    target = pathlib.Path("jupyterlite/content")

    if not source.is_dir():
        print(f"error: {source} not found; run from repo root", file=sys.stderr)
        return 1

    target.mkdir(parents=True, exist_ok=True)

    copied = 0
    for nb_path in sorted(source.glob("*.ipynb")):
        # Skip landing pages -- each directory has its own
        if nb_path.name.startswith("00_"):
            continue

        nb = nbformat.read(nb_path, as_version=4)

        # Inject %pip install cell at the top if not already present
        if not _has_pip_install(nb):
            pip_cell = nbformat.v4.new_code_cell(_PIP_CELL_SOURCE)
            pip_cell.metadata["tags"] = ["remove-output"]
            nb.cells.insert(0, pip_cell)

        nbformat.write(nb, target / nb_path.name)
        copied += 1
        print(f"  {nb_path.name}")

    print(f"Copied {copied} notebooks from {source}/ to {target}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
