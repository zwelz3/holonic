"""Structural guards for the documentation tree.

Regression classes pinned by tests (the first two surfaced in the v0.7.1 audit):

- **toctree drops core docs.** ``docs/source/index.md`` used to point its
  "Project" toctree at ``../SPEC`` / ``../DECISIONS`` / ``../MIGRATION`` /
  ``../../CHANGELOG`` -- paths Sphinx cannot resolve, so those documents were
  silently omitted from the built site. They are now first-class pages
  (``docs/source/{spec,decisions,migration,changelog}.md`` include-shims).
  ``test_index_toctree_entries_resolve`` fails if any toctree entry stops
  resolving to a real document again.

- **dangling ``verifiedBy:`` links.** ``docs/SPEC.md`` annotates each
  requirement with the test that verifies it. Tests were renamed/reorganized
  into classes over many releases, so ~36 of these citations pointed at node
  IDs that no longer exist -- traceability that reads as green but proves
  nothing. ``test_spec_verifiedby_links_resolve`` statically resolves every
  node-form citation against the actual test tree, so a future rename that
  orphans a link fails here instead of rotting silently.

- **``constrains:`` items split inside parentheses.** specl splits a
  ``constrains:`` or ``affects:`` value on every comma (specl's SYNTAX.md,
  "Comma-split"), including one inside a parenthesized symbol list, so
  ``holonic/client.py (freshness, is_stale)`` became two components,
  ``holonic/client.py (freshness`` and ``is_stale)``. Seven
  requirements emitted sixteen malformed ``specl:Component`` identifiers this
  way. ``test_spec_constrains_items_have_no_comma_inside_parentheses`` fails on
  the pattern in ``SPEC.md``, where the malformed components originate.

The tests only run from a source checkout; against an installed wheel the
prose/source files are absent and the tests skip.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest


def _find_repo_root() -> pathlib.Path | None:
    """Locate the source checkout by walking up from this file."""
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "docs" / "SPEC.md").is_file():
            return parent
    return None


ROOT = _find_repo_root()

needs_checkout = pytest.mark.skipif(
    ROOT is None,
    reason="not running from a source checkout; docs sources unavailable",
)


# ── toctree resolution ──────────────────────────────────────────────────────

_TOCTREE_OPTION = re.compile(r"^\s*:[\w-]+:")


def _iter_toctree_entries(markdown: str) -> list[str]:
    """Yield every document entry across all ``{toctree}`` fences in *markdown*.

    Skips the fence markers, the ``:option:`` lines, and blank lines. A
    ``:glob:`` block is reported separately so the caller can relax the
    exact-file check (globs legitimately name patterns, not documents).
    """
    entries: list[tuple[str, bool]] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        if re.match(r"^```+\{toctree\}", lines[i].strip()):
            i += 1
            is_glob = False
            block: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            for raw in block:
                if _TOCTREE_OPTION.match(raw):
                    if raw.strip().startswith(":glob:"):
                        is_glob = True
                    continue
                entry = raw.strip()
                if entry:
                    entries.append((entry, is_glob))
        i += 1
    return [e for e, _ in entries if not _]  # non-glob entries only


@needs_checkout
def test_index_toctree_entries_resolve() -> None:
    """Every non-glob toctree entry must resolve to a real source document."""
    assert ROOT is not None
    source = ROOT / "docs" / "source"
    index = (source / "index.md").read_text(encoding="utf-8")

    missing = []
    for entry in _iter_toctree_entries(index):
        # Entries are extension-less doc names relative to docs/source.
        candidates = [source / f"{entry}.md", source / f"{entry}.rst", source / entry]
        if not any(c.exists() for c in candidates):
            missing.append(entry)

    assert not missing, (
        "docs/source/index.md toctree references documents that do not exist "
        f"under docs/source/: {missing}. Add the page (or an include-shim), or "
        "remove the entry -- an unresolved toctree entry silently drops the doc "
        "from the built site."
    )


# ── verifiedBy resolution ───────────────────────────────────────────────────

_VERIFIED_BY = re.compile(r"^\s*-\s*verifiedBy:\s*(.+?)\s*$", re.MULTILINE)


def _node_tokens(value: str) -> list[str]:
    """Extract the pytest-node-id tokens from a ``verifiedBy`` value.

    Values may be prose (``none``, ``(pending implementation)``), a bare file
    path (structural refs), or one-or-more ``path::Class::method`` node IDs
    joined by commas / the word "and". Only the node-form tokens are returned;
    everything else is intentionally unchecked.
    """
    tokens = re.split(r",|\band\b", value)
    return [t.strip().rstrip(".,") for t in tokens if "::" in t]


def _resolve_node(root: pathlib.Path, node: str) -> str | None:
    """Return an error string if *node* does not resolve, else ``None``.

    Resolution is static (``ast``): the file must exist and each ``::`` segment
    must name a class or function defined at the appropriate nesting level.
    """
    path_part, *segments = node.split("::")
    path = root / path_part
    if not path.is_file():
        return f"file not found: {path_part}"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - a broken test file is its own failure
        return f"could not parse {path_part}: {exc}"

    scope: list[ast.stmt] = tree.body
    trail = path_part
    for seg in segments:
        match = next(
            (
                n
                for n in scope
                if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == seg
            ),
            None,
        )
        if match is None:
            return f"'{seg}' not found in {trail}"
        trail = f"{trail}::{seg}"
        scope = match.body if isinstance(match, ast.ClassDef) else []
    return None


@needs_checkout
def test_spec_verifiedby_links_resolve() -> None:
    """Every node-form ``verifiedBy:`` in SPEC.md must name a real test.

    Prose markers (``none``, ``(pending ...)``) and bare structural file paths
    carry no ``::`` and are skipped -- this guards the traceability links, not
    test coverage itself.
    """
    assert ROOT is not None
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")

    failures: list[str] = []
    checked = 0
    for value in _VERIFIED_BY.findall(spec):
        for node in _node_tokens(value):
            checked += 1
            err = _resolve_node(ROOT, node)
            if err is not None:
                failures.append(f"{node} -- {err}")

    assert checked, "no node-form verifiedBy links found; parser or SPEC.md changed shape"
    assert not failures, (
        "docs/SPEC.md has verifiedBy links that no longer resolve to a test "
        "(rename the citation to the current node id, or mark it "
        "'verifiedBy: none'):\n  " + "\n  ".join(failures)
    )


# ── constrains: component lists ─────────────────────────────────────────────

_COMMA_SPLIT = re.compile(r"^\s*- (?:constrains|affects):\s*(.+)$", re.MULTILINE)


def _commas_inside_parentheses(value: str) -> bool:
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth > 0:
            return True
    return False


@needs_checkout
def test_spec_constrains_items_have_no_comma_inside_parentheses() -> None:
    """Each ``constrains:`` and ``affects:`` item must survive specl's comma split.

    specl does not respect parentheses when it splits these values, so
    ``path (a, b)`` must be written ``path (a), path (b)``.
    """
    assert ROOT is not None
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    values = _COMMA_SPLIT.findall(spec)
    assert values, "no constrains: annotations found; parser or SPEC.md changed shape"
    offending = [v for v in values if _commas_inside_parentheses(v)]
    assert not offending, (
        "docs/SPEC.md has constrains:/affects: values with a comma inside parentheses, "
        "which specl splits into malformed components (write 'path (a), path (b)'):\n  "
        + "\n  ".join(offending)
    )
