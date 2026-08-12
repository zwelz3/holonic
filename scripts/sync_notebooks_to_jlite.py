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

Widget packages get their version pinned on the way through. ipywidgets
resolves a widget's frontend labextension by name and semver, and that
labextension is baked into the site by ``jupyter lite build`` from whatever
is installed here. If the browser installs a different version off PyPI the
widget renders an empty output area instead of raising, so the pin is
rewritten to the version present in this environment rather than left to
resolve at runtime.

Also writes jupyterlite/jupyter-lite.json, keying the browser contents
store to a hash of the notebooks so a new build supersedes the copies
JupyterLite persists in IndexedDB. Note this is the *runtime* config
shipped to the browser, not the build-time jupyter_lite_config.json.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import pathlib
import re
import sys

import nbformat


# Marker kept out of the cell body so detection survives edits to the snippet.
_PIP_MARKER = "# holonic-jlite-install"

# Fixed cell id. ``new_code_cell`` mints a random one per call, which would
# leave every notebook dirty after each sync even when nothing changed.
_PIP_CELL_ID = "holonic-jlite-install"

_PIP_CELL_SOURCE = """# holonic-jlite-install
# The retry is deliberate: a stale browser cache can leave a partial wheel
# behind, and a plain install keeps failing until the user clears the cache
# or opens a private tab. --force-reinstall gets them past it.
try:
    %pip install --quiet holonic
except Exception:
    try:
        %pip install --quiet holonic --force-reinstall
    except Exception:
        print(
            "holonic failed to install. Your browser may be holding a partial "
            "wheel: reopen this page in a private window, or clear site data "
            "for this origin, then re-run this cell."
        )
        raise

import holonic
print(f"holonic {holonic.__version__}")
"""


# Marker on the notebook-supplied viz install cell (13_visualization.ipynb).
# Kept out of the cell body for the same reason as _PIP_MARKER.
_VIZ_MARKER = "# holonic-viz-install"

# Widget distributions whose Python version must match the labextension that
# ``jupyter lite build`` bundles into the site.
_PINNED_WIDGETS = ("yfiles-jupyter-graphs",)


def _pin_widget_versions(nb: nbformat.NotebookNode, name: str) -> list[str]:
    """Rewrite widget requirements in the viz install cell to exact pins.

    Returns the pins applied, for logging. A distribution that is not
    installed here is left alone: this environment is also what supplies the
    labextension, so if it is absent there is no bundled frontend to match
    and an exact pin would be a guess.
    """
    applied: list[str] = []

    for cell in nb.cells:
        if cell.cell_type != "code" or _VIZ_MARKER not in cell.source:
            continue

        for dist in _PINNED_WIDGETS:
            try:
                version = importlib.metadata.version(dist)
            except importlib.metadata.PackageNotFoundError:
                print(
                    f"  warning: {dist} not installed; leaving the pin in "
                    f"{name} as-is. The browser will resolve it from PyPI and "
                    f"may not match the bundled labextension.",
                    file=sys.stderr,
                )
                continue

            # Matches the quoted requirement with any specifier, or none: the
            # pin is rewritten on every sync, so a re-pin must overwrite an
            # existing pin rather than stack onto it.
            #
            # Deliberately strict about what may follow the distribution name:
            # a specifier character, then non-space, non-quote characters up to
            # the closing quote. Requirements never contain spaces, but prose
            # does, and the cell mentions this distribution in both its version
            # echo (``"yfiles-jupyter-graphs {...}"``) and its error message
            # (``"yfiles-jupyter-graphs < 2 to match ..."``). Looser patterns
            # rewrote both into a requirement string.
            pattern = re.compile(rf'"{re.escape(dist)}(?:[<>=!~,][^"\s]*)?"')
            pinned = f'"{dist}=={version}"'
            cell.source, count = pattern.subn(pinned, cell.source)
            if count:
                applied.append(f"{dist}=={version}")
            else:
                print(
                    f"  warning: no {dist} requirement found in {name} "
                    f"despite the {_VIZ_MARKER} marker; nothing pinned.",
                    file=sys.stderr,
                )

    return applied


def _make_pip_cell() -> nbformat.NotebookNode:
    """Build the install cell with a stable id so syncs stay reproducible."""
    cell = nbformat.v4.new_code_cell(_PIP_CELL_SOURCE)
    cell.metadata["tags"] = ["remove-output"]
    cell["id"] = _PIP_CELL_ID
    return cell


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
        nb.cells.insert(1 if nb.cells else 0, _make_pip_cell())

    nbformat.write(nb, landing)
    return True


def _content_hash(target: pathlib.Path) -> str:
    """Hash the synced notebooks, stably across platforms.

    ``nbformat.write`` emits platform-native line endings, so hashing raw bytes
    would give a Windows checkout and Linux CI different answers and leave
    ``jupyter-lite.json`` permanently dirty. Normalize before hashing.
    """
    digest = hashlib.sha256()
    for path in sorted(target.glob("*.ipynb")):
        digest.update(path.name.encode("utf-8"))
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        digest.update(text.encode("utf-8"))
    return digest.hexdigest()[:12]


def _write_storage_stamp(target: pathlib.Path) -> bool:
    """Stamp ``contentsStorageName`` with a hash of the notebook content.

    JupyterLite copies a notebook into browser IndexedDB the first time it is
    opened and run, and from then on that local copy shadows whatever the site
    serves. A reader who visited before a fix shipped keeps running the old
    cell, with no indication anything is stale -- and no fix inside the cell can
    reach them, because their copy contains the *old* cell.

    Keying the storage name to the content sidesteps that: new notebooks mean a
    different IndexedDB database, so the served copy wins. Reloads in between
    deploys still persist normally.

    Only contents are stamped. Settings and workspaces hold theme and layout
    preferences that have nothing to do with staleness, so they are left alone.
    """
    lite_json = target.parent / "jupyter-lite.json"

    config: dict = {}
    if lite_json.is_file():
        config = json.loads(lite_json.read_text(encoding="utf-8"))

    config.setdefault("jupyter-lite-schema-version", 0)
    config_data = config.setdefault("jupyter-config-data", {})

    name = f"holonic-jlite-{_content_hash(target)}"
    if config_data.get("contentsStorageName") == name:
        return False

    config_data["contentsStorageName"] = name
    lite_json.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
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
            nb.cells.insert(0, _make_pip_cell())

        # Pin widget versions to this environment, which is also what supplies
        # the labextensions the build bundles.
        pins = _pin_widget_versions(nb, nb_path.name)

        nbformat.write(nb, target / nb_path.name)
        copied += 1
        suffix = f" (pinned {', '.join(pins)})" if pins else ""
        print(f"  {nb_path.name}{suffix}")

    print(f"Copied {copied} notebooks from {source}/ to {target}/")

    if _sync_landing_install_cell(target):
        print("  00_start_here.ipynb (install cell refreshed)")

    # After the landing page, so its install cell is part of the hash.
    if _write_storage_stamp(target):
        print("  jupyter-lite.json (contents storage name restamped)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
