"""Version consistency across the repo's hand-maintained references.

``holonic.__version__`` is the single source of truth. ``pyproject.toml``
derives from it (flit ``dynamic = ["version"]``) and ``docs/source/conf.py``
reads it back out of the installed metadata, so neither of those can drift
without the build itself changing.

What remains are prose files a human edits at release time:

- ``CHANGELOG.md`` -- checked hard. A release whose top entry names a
  different version is a defect readers see on PyPI and GitHub.
- ``docs/SPEC.md`` -- checked soft. The spec carries its own version and may
  legitimately diverge (a wording clarification need not imply a library
  release), so a mismatch is a warning rather than a failure. Under GitHub
  Actions it also surfaces as a workflow annotation on the offending line.

``docs/SPEC.ttl`` is generated from ``docs/SPEC.md`` by the ``spec-translate``
pixi task, so its ``dct:hasVersion`` follows the frontmatter automatically and
is not checked separately.
"""

from __future__ import annotations

import os
import pathlib
import re
import warnings

import pytest

import holonic


def _find_repo_root() -> pathlib.Path | None:
    """Locate the source checkout by walking up from this file.

    Returns ``None`` when the suite runs against an installed wheel, where
    the repo's prose files are simply not present.
    """
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "CHANGELOG.md").is_file():
            return parent
    return None


ROOT = _find_repo_root()

needs_checkout = pytest.mark.skipif(
    ROOT is None,
    reason="not running from a source checkout; prose files unavailable",
)


def test_changelog_top_entry_matches_version() -> None:
    """The newest CHANGELOG heading must name the current version."""
    if ROOT is None:
        pytest.skip("not running from a source checkout")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^##\s*\[([^\]]+)\]", changelog, re.MULTILINE)
    assert match is not None, "CHANGELOG.md has no '## [<version>]' heading"

    heading = match.group(1).strip()
    if heading.lower() == "unreleased":
        pytest.skip("top CHANGELOG entry is [Unreleased]; nothing to compare")

    assert heading == holonic.__version__, (
        f"CHANGELOG.md's top entry is [{heading}] but holonic.__version__ is "
        f"{holonic.__version__}. Add the release entry, or correct "
        f"__version__ in src/holonic/__init__.py."
    )


@needs_checkout
def test_spec_version_tracks_package_version(capsys: pytest.CaptureFixture) -> None:
    """Warn -- never fail -- when docs/SPEC.md's version drifts.

    The two are expected to move together in practice, but the spec is
    allowed its own cadence, so this reports rather than enforces.
    """
    assert ROOT is not None  # narrowed by needs_checkout
    spec = ROOT / "docs" / "SPEC.md"
    if not spec.is_file():
        pytest.skip("docs/SPEC.md not present")

    lines = spec.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        pytest.skip("docs/SPEC.md has no YAML frontmatter block")

    spec_version: str | None = None
    line_no = 0
    for offset, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            break
        found = re.match(r"\s*version\s*:\s*(\S+)", line)
        if found:
            spec_version = found.group(1).strip("\"'")
            line_no = offset
            break

    if spec_version is None:
        pytest.skip("docs/SPEC.md frontmatter has no 'version:' key")

    if spec_version == holonic.__version__:
        return

    message = (
        f"docs/SPEC.md declares version {spec_version} but holonic.__version__ "
        f"is {holonic.__version__}. This is allowed -- the spec may version "
        f"independently -- but confirm the divergence is intentional."
    )
    warnings.warn(message, UserWarning, stacklevel=1)

    if os.environ.get("GITHUB_ACTIONS") == "true":
        # Annotations must reach the real stdout; pytest captures at the fd
        # level and swallows output from passing tests. The leading newline
        # matters: GitHub only parses a workflow command at column 0, and
        # pytest's progress characters leave the cursor mid-line.
        with capsys.disabled():
            print(
                f"\n::warning file=docs/SPEC.md,line={line_no},title=Spec version drift::{message}"
            )
