"""Sphinx configuration for holonic documentation."""

import os
import pathlib
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "holonic"
copyright = "2026, Zachary Welz"
author = "Zachary Welz"
release = "0.4.2"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "myst_parser",
]

# MyST for markdown support
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "_extra"]

html_theme = "sphinx_rtd_theme"

# Conditionally include static/extra paths so Sphinx doesn't warn
# when they don't exist (e.g. local docs build without a prior
# JupyterLite build, or no custom static assets).
_source_dir = pathlib.Path(__file__).parent
html_static_path = ["_static"] if (_source_dir / "_static").is_dir() else []

# JupyterLite build output goes into _extra/jupyterlite/ via RTD
# pre_build, GitHub Actions CI, or `pixi run build_jl`.
# html_extra_path copies the contents verbatim into the Sphinx output
# root, so the site is served at /jupyterlite/index.html with no
# Sphinx processing (no path rewriting, no checksum suffixing).
html_extra_path = ["_extra"] if (_source_dir / "_extra").is_dir() else []

# Autodoc settings
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

# Intersphinx mapping
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "rdflib": ("https://rdflib.readthedocs.io/en/stable/", None),
}

# Napoleon settings (Google-style docstrings)
napoleon_google_docstrings = True
napoleon_numpy_docstrings = True
napoleon_include_init_with_doc = True
