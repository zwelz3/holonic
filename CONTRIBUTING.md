# Contribution Guide

All contributions, bug reports, bug fixes, documentation improvements, enhancements, and ideas are welcome.

## How do I report an issue?

Using the [Github issues] feature, please explain in as much detail as possible:

1. The Python version and environment
2. How `holonic` was installed
3. A minimum working example of the bug, along with any output/errors.

Bug reports and enhancement requests are an important part of making `holonic` more stable. If you wish to contribute, then please be sure
there is an active issue to work against. If there is not one please create one.

## How do I put in a good PR?

### Create a Fork

You will need your own copy of `holonic` (aka fork) to work on the code. Go to the [`holonic` project page] and hit the `Fork` button.

### Set Up the Development Environment

1. Get [`pixi`](https://pixi.sh).
2. Use `pixi run -e dev first`

That will give you an editable install in to the `dev` local environment managed by `pixi`. It also runs the lint,
tests, and builds the docs. Any errors from that command should be reported as issues.

### Code Quality and Testing

1. Use `pixi r -e dev lint-fix`, and `pixi r -e dev lint-check` to run style/formatting/typing checks.
2. Use `pixi r -e dev test` to run the tests
3. If you modify the docs, use `pixi r -e dev build_html_docs` to ensure they build.

Code quality is enforced using the following tools:

1. [`pyproject-fmt`](https://pyproject-fmt.readthedocs.io/en/latest/) - pyproject.toml formatter
2. [`ssort`](https://pyproject-fmt.readthedocs.io/en/latest/) - source code sorter
3. [`ruff`](https://docs.astral.sh/ruff/) - linter and code formatter
4. [`mypy`](https://mypy-lang.org/) - static type checker

### Specl (optional, for spec work)

`docs/SPEC.md` is validated by [specl](https://github.com/zwelz3/specl), which is pulled from git and kept out of the `dev` environment so day-to-day work doesn't depend on it. If you touch the SPEC, work in the dedicated `spec` environment:

```bash
pixi run -e spec spec-translate   # docs/SPEC.md -> docs/SPEC.ttl
pixi run -e spec spec-validate    # SHACL validation with explanations
pixi run -e spec spec-score       # maturity score (0-100%)
pixi run -e spec spec-badge       # generate build/spec-badge.svg
```

First invocation materializes the `spec` environment and resolves the specl git pin; subsequent runs reuse the resolved environment.

### Style Guide

For style, see [STYLE_GUIDE](STYLE_GUIDE.md).

## Making Pull Requests

The valid target for all pull requests is `main`. Please ensure that your pull request includes
documentation and explanation for its purpose and sufficient documentation to explain its usage.

> **TBD (post-1.0):** a long-lived `dev` branch is planned once the API stabilizes at `1.0`.
> At that point `dev` becomes the default PR target and `main` tracks released versions only.
> Until then, `main` is the single target — not to be confused with the `dev` *pixi
> environment* (`pixi run -e dev ...`), which is unrelated.

## Versioning

### There is exactly one version to edit

`__version__` in [`src/holonic/__init__.py`](src/holonic/__init__.py) is the single source of
truth. To change the version, edit that one line. Nothing else.

Two files **derive** from it automatically — do not edit them, and revert them if a tool does:

| File | How it derives |
| --- | --- |
| `pyproject.toml` | `dynamic = ["version"]`; flit reads `__version__` out of the module at build time |
| `docs/source/conf.py` | `importlib.metadata.version("holonic")` |

Two files are **checked** against it, because they are prose a human writes:

| File | On mismatch |
| --- | --- |
| `CHANGELOG.md` (newest `## [x.y.z]` heading) | Test failure. A release whose changelog names a different version is a defect readers see on PyPI and GitHub. |
| `docs/SPEC.md` (frontmatter `version:`) | Warning only. The spec is allowed its own cadence — a wording clarification need not imply a library release — so confirm the divergence is intentional and move on. |

`docs/SPEC.ttl` is generated from `docs/SPEC.md` by `pixi run -e spec spec-translate`, so its
`dct:hasVersion` follows the frontmatter and is never edited by hand.

Both checks live in `src/holonic/test/test_version_consistency.py` and run as part of
`pixi r -e dev test`.

### The release cycle

Versions follow [PEP 440](https://peps.python.org/pep-0440/). Between releases the version
carries a `.dev0` suffix and `CHANGELOG.md` opens with `## [Unreleased]`; the changelog check
skips while that heading is in place, so day-to-day PRs are unaffected.

1. **Cut the release.** Drop the `.dev0` suffix from `__version__`, and rename the
   `## [Unreleased]` changelog heading to `## [x.y.z] - <date>`. The two must agree or CI fails.
2. **Merge the release PR, then tag `vx.y.z` on the merge commit and push the tag.** The tag
   is what triggers the PyPI publish job in `.github/workflows/ci.yml`.
3. **Open the next cycle.** File a post-release PR using the
   [post-release template](.github/PULL_REQUEST_TEMPLATE/post-release.md): bump `__version__`
   to the next `.dev0`, reopen `## [Unreleased]`, and record what went wrong so the next
   release goes better. Open it with:

   ```text
   https://github.com/zwelz3/holonic/compare/main...<your-branch>?template=post-release.md
   ```
