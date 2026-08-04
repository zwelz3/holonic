"""Copy example notebooks from notebooks/ into jupyterlite/content/.

Keeps the two directories in sync so the next ``pixi run build_jl``
picks up any changes. The landing notebook (00_start_here.ipynb) has no
counterpart under notebooks/ -- it is JupyterLite-specific -- so it is
never overwritten. Its install cell is still rewritten in place, because
that snippet must not drift from the one injected everywhere else.

Each copied notebook gets an install cell injected at the top so that
holonic is available regardless of which notebook the user opens first.
Nothing pre-installs holonic into the Pyodide environment, so every
notebook has to install it for itself.
"""

from __future__ import annotations

import pathlib
import sys

import nbformat


# Marker kept out of the cell body so detection survives edits to the snippet.
_PIP_MARKER = "# holonic-jlite-install"

_PIP_CELL_SOURCE = """# holonic-jlite-install
# The retry is deliberate: a stale browser cache can leave a partial wheel
# behind, and a plain install keeps failing until the user clears the cache
# or opens a private tab. --force-reinstall gets them past it.
try:
    %pip install --quiet holonic
except Exception:
    %pip install --quiet holonic --force-reinstall

import holonic
print(f"holonic {holonic.__version__}")
"""


def _has_pip_install(nb: nbformat.NotebookNode) -> bool:
    """Check if the notebook already has the injected install cell."""
    for cell in nb.cells:
        if cell.cell_type == "code" and _PIP_MARKER in cell.source:
            return True
    return False


def _sync_landing_install_cell(target: pathlib.Path) -> bool:
    """Rewrite the landing notebook's install cell from ``_PIP_CELL_SOURCE``.

    ``00_start_here.ipynb`` is hand-maintained (its markdown indexes every
    notebook), so it is never copied over. Only the install cell is touched,
    which keeps it from drifting out of sync with the injected one.
    """
    landing = target / "00_start_here.ipynb"
    if not landing.is_file():
        return False

    nb = nbformat.read(landing, as_version=4)

    for cell in nb.cells:
        if cell.cell_type != "code" or "%pip install" not in cell.source:
            continue
        if cell.source == _PIP_CELL_SOURCE:
            return False
        cell.source = _PIP_CELL_SOURCE
        cell.metadata["tags"] = ["remove-output"]
        break
    else:
        # No install cell at all -- reinstate one. The smoke test further down
        # imports holonic, so the landing page breaks without it.
        pip_cell = nbformat.v4.new_code_cell(_PIP_CELL_SOURCE)
        pip_cell.metadata["tags"] = ["remove-output"]
        nb.cells.insert(1 if nb.cells else 0, pip_cell)

    nbformat.write(nb, landing)
    return True


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

    if _sync_landing_install_cell(target):
        print("  00_start_here.ipynb (install cell refreshed)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
