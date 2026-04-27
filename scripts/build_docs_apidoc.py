#!/usr/bin/env python3
"""
Regenerate per-library autodoc .rst stubs for the ODT Platform.

Replaces the broken `sphinx-apidoc -f -o ./docs/source/auto .` command
that crawls the entire repo root. This script iterates over each
library under ``libraries/`` and invokes sphinx-apidoc against only
that library's package directory.

Services are NOT processed — they have their own documentation trees
and will be wrapped via MyST include directives in
``docs/source/services/<name>.md``.

Usage (via pixi)::

    pixi run -e dev autogen

Usage (directly)::

    python scripts/build_docs_apidoc.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LIBRARIES_DIR = ROOT / "libraries"
DOCS_AUTO_DIR = ROOT / "docs" / "source" / "libraries" / "auto"


def find_library_packages() -> list[tuple[str, Path]]:
    """Return (library_name, package_src_dir) pairs for every library.

    Assumes the odt convention: ``libraries/<libname>/src/<pkg>/``
    where ``<libname>`` uses hyphens and ``<pkg>`` uses underscores.
    """
    found: list[tuple[str, Path]] = []
    for lib_dir in sorted(LIBRARIES_DIR.iterdir()):
        if not lib_dir.is_dir() or lib_dir.name.startswith("."):
            continue
        src = lib_dir / "src"
        if not src.is_dir():
            print(
                f"[skip] {lib_dir.name}: no src/ directory",
                file=sys.stderr,
            )
            continue
        # Find the first package directory under src/ (one per library
        # by convention).
        pkg_dirs = [
            p for p in src.iterdir()
            if p.is_dir() and (p / "__init__.py").exists()
        ]
        if not pkg_dirs:
            print(
                f"[skip] {lib_dir.name}: no importable package under src/",
                file=sys.stderr,
            )
            continue
        if len(pkg_dirs) > 1:
            print(
                f"[warn] {lib_dir.name}: multiple packages under src/; "
                f"documenting only {pkg_dirs[0].name}",
                file=sys.stderr,
            )
        found.append((lib_dir.name, pkg_dirs[0]))
    return found


def run_apidoc(library_name: str, package_dir: Path) -> int:
    """Invoke sphinx-apidoc for one library.

    Writes into ``docs/source/libraries/auto/<package_name>/``.
    """
    out_dir = DOCS_AUTO_DIR / package_dir.name
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sphinx-apidoc",
        "--force",                 # overwrite existing files
        "--module-first",          # module doc before submodules
        "--separate",              # one file per module
        "--output-dir", str(out_dir),
        str(package_dir),
    ]
    print(f"[apidoc] {library_name} -> {out_dir}")
    return subprocess.call(cmd)


def main() -> int:
    if not LIBRARIES_DIR.is_dir():
        print(f"Error: {LIBRARIES_DIR} not found", file=sys.stderr)
        return 2
    DOCS_AUTO_DIR.mkdir(parents=True, exist_ok=True)

    libraries = find_library_packages()
    if not libraries:
        print("No libraries found.", file=sys.stderr)
        return 1

    failures = 0
    for name, pkg in libraries:
        rc = run_apidoc(name, pkg)
        if rc != 0:
            failures += 1
            print(f"[fail] {name} (sphinx-apidoc exit={rc})", file=sys.stderr)

    print(f"Done. {len(libraries) - failures}/{len(libraries)} libraries OK.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
