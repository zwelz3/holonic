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

### Style Guide

For style, see [STYLE_GUIDE](STYLE_GUIDE.md).

## Making Pull Requests

The valid target for all pull requests is `dev`. Please ensure that your pull request includes
documentation and explanation for its purpose and sufficient documentation to explain its usage.
