# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
import os
import sys

from datetime import datetime

import holonic

sys.path.insert(0, os.path.abspath("../../src"))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/mast er/usage/configuration.html#project-information

project = "holonic"
copyright = f"{datetime.now().year}, {holonic.__authors__}"
author = holonic.__authors__
release = holonic.__version__

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.coverage",
    "sphinx.ext.githubpages",
    "myst_parser",
]
templates_path = ["_templates"]
nbsphinx_allow_errors = True
add_module_names = False

autodoc_default_options = {
    "ignore-module-all": True,
}

# ---- MYST options -----------
myst_enable_extensions = ["colon_fence", "substitution"]
myst_heading_anchors = 2
myst_substitutions = {
    "rtd": "[Read the Docs](https://readthedocs.org/)",
}


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]
html_logo = "logo.png"
html_show_sourcelink = False
html_theme_options = {
  "show_nav_level": 2,
  "navbar_center": ["navbar-nav"],
  "logo": {
        "text": "holonic",
    },
  "show_toc_level": 1,
    "icon_links": [
        {
            "name": "GitHub",
            "url": "todo",
            "icon": "fa-brands fa-square-github",
            "type": "fontawesome",
        },
    ]
}
