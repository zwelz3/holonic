# Post-release: open the `A.B.C` cycle

Filed after `vX.Y.Z` was tagged and published. This PR does two jobs: confirm the release
actually landed, and open the next development cycle so `main` is ready for normal work.

Replace `X.Y.Z` (just released) and `A.B.C` (next) throughout, and delete any section that
genuinely does not apply — but say why rather than deleting it silently.

Released version: `X.Y.Z` · Tag: `vX.Y.Z` · Next version: `A.B.C.dev0`

---

## 1. Confirm the release landed

Do this before bumping anything. If the publish failed, the fix is to re-cut `X.Y.Z`, not to
move on to `A.B.C`.

- [ ] Tag `vX.Y.Z` exists on `main` and points at the intended commit
- [ ] The **Publish to PyPI** job succeeded for that tag
- [ ] `pip install holonic==X.Y.Z` works in a clean environment, and
      `python -c "import holonic; print(holonic.__version__)"` prints `X.Y.Z`
- [ ] Docs are deployed and show `X.Y.Z` (GitHub Pages and Read the Docs)
- [ ] The JupyterLite notebooks on the published docs site execute against `X.Y.Z`
- [ ] GitHub release notes exist for `vX.Y.Z` and match `CHANGELOG.md`

## 2. Open the next cycle

These are the actual changes in this PR.

- [ ] `src/holonic/__init__.py` — `__version__ = "A.B.C.dev0"`

      This is the **only** version edit. `pyproject.toml` and `docs/source/conf.py` derive
      from it (flit `dynamic`, and `importlib.metadata` respectively). If a tool touched
      either one, revert it.

- [ ] `CHANGELOG.md` — add a `## [Unreleased]` heading above the `## [X.Y.Z]` entry

      The changelog check skips while `[Unreleased]` is the top heading, which is what makes
      routine PRs possible mid-cycle. Without it, CI fails immediately on the `.dev0` bump.

- [ ] `docs/SPEC.md` — frontmatter `version:`

      Update it to `A.B.C.dev0` if the spec is tracking the library, or leave it and note the
      reason below. A mismatch is a warning, never a failure — the spec is allowed its own
      cadence.

      <!-- If leaving it: why? -->

- [ ] If `docs/SPEC.md` changed, regenerate the Turtle: `pixi run -e spec spec-translate`
- [ ] No edits to `pyproject.toml` or `docs/source/conf.py` in this diff

## 3. Post-mortem

The point of the exercise. Be specific and blameless — the goal is that `A.B.C` is smoother
than `X.Y.Z`, not that anyone feels bad about `X.Y.Z`.

**What shipped.** One or two sentences on the headline of this release.

<!-- ... -->

**What went wrong, or was more painful than it should have been.** Include near-misses and
things caught late in review — those are the cheapest lessons available.

<!-- ... -->

**Did anything break after publishing?** Yanked releases, hotfixes, broken docs builds, user
reports. If nothing, say "nothing" — a clean record is worth having.

<!-- ... -->

**What would have caught it earlier?** A test, a CI gate, a checklist line, a doc. Prefer an
automated check over a note asking humans to remember.

<!-- ... -->

**Follow-ups filed.** Link the issues. Anything not filed here will be forgotten by `A.B.C`.

<!-- - #NNN ... -->

## 4. Verify before merging

```bash
pixi r -e dev lint-check
pixi r -e dev test          # includes the version-consistency checks
pixi r -e dev build_html_docs
```

- [ ] `pixi r -e dev test` passes
- [ ] The version-consistency test reports no unexpected spec-drift warning
      (a warning is fine if section 2 explains it)
