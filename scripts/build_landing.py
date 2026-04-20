"""Rebuild jupyterlite/content/00_start_here.ipynb with accurate
notebook-level guidance.
"""

import nbformat as nbf

nb = nbf.v4.new_notebook()

cells = [
    nbf.v4.new_markdown_cell("""# Welcome to holonic (in-browser)

You're running holonic in [JupyterLite](https://jupyterlite.readthedocs.io/), a Python environment that runs entirely in your browser via [Pyodide](https://pyodide.org/). No installation required. Your work is saved to browser storage, so bookmarks work, but don't expect this to survive a hard cache clear.

## What works here

Everything the `holonic` library does that doesn't require external services:

- ✅ Four-graph holon model (`HolonicDataset`, `add_holon`, `add_interior`, `add_boundary`)
- ✅ Portal traversal with PROV-O provenance
- ✅ Membrane validation via SHACL (pyshacl runs in pyodide)
- ✅ Projections (CONSTRUCT + Python transforms)
- ✅ Scope resolution across the holarchy
- ✅ Projection pipelines with the plugin system
- ✅ Dispatch patterns (synchronous, event-queue, asyncio) — notebook 10

## What doesn't work here

- ❌ `FusekiBackend` — no HTTP in the browser sandbox
- ❌ `yfiles-jupyter-graphs` visualization widgets (notebook 11) — requires a Jupyter server extension that pyodide can't provide
- ❌ `holonic-migrate-registry` CLI — no subprocess invocation in pyodide

If you want the full feature set, install locally with `pip install holonic` and clone the example notebooks from the repository.

## First run: install holonic

The cell below installs holonic into the pyodide environment. Run this once per session; subsequent notebooks inherit the installed package."""),

    nbf.v4.new_code_cell("""%pip install --quiet holonic

import holonic
print(f"holonic version: {holonic.__version__}")"""),

    nbf.v4.new_markdown_cell("""## Smoke test

A minimal holarchy to confirm everything works."""),

    nbf.v4.new_code_cell("""from holonic import HolonicDataset

ds = HolonicDataset()

ds.add_holon("urn:holon:demo", "Demo Holon")
ds.add_interior("urn:holon:demo", '''
    @prefix schema: <https://schema.org/> .
    <urn:item:1> a schema:Thing ;
        schema:name "Hello from the browser" .
''')

print(ds.summary())"""),

    nbf.v4.new_markdown_cell("""## Explore the example notebooks

The file browser on the left side has the full set of example notebooks:

- **01–05** — Foundations: holons, portals, translation, projections, topology visualization
- **06** — Console dataclasses for web UI consumption
- **07** — Graph-level metadata (triple counts, class inventory, refresh policies)
- **08** — Scope resolution (BFS predicates over the holarchy)
- **09** — Projection plugins (entry-point-discovered transforms)
- **10** — Dispatch patterns (synchronous, event-queue, asyncio)
- **11** — Interactive visualization (won't run here; local Jupyter only)

Start with `01_holon_basics.ipynb` if this is your first time.

Notebooks 01–10 use only the base `holonic` package which you installed above. Notebook 11 attempts to install `holonic[viz]` for yFiles widgets, but the yFiles JupyterLab extension is not available in Pyodide — so that notebook is better run locally."""),
]

nb.cells = cells
nbf.write(nb, "jupyterlite/content/00_start_here.ipynb")
print("Rewrote landing notebook")
