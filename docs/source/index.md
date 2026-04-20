# holonic — Graph-Native Holonic RDF Systems

```{toctree}
:maxdepth: 2
:caption: Contents

api
projections
backends
ontology
dom-comparison
```

```{toctree}
:maxdepth: 1
:caption: Project
:glob:

../SPEC
../DECISIONS
../MIGRATION
../../CHANGELOG
```

## Overview

`holonic` is a lightweight Python client for building holonic
knowledge graphs backed by rdflib, Apache Jena Fuseki, or any
SPARQL-compliant quad store.

A holon is an IRI whose associated named graphs exist in an RDF
dataset. The dataset IS the holarchy — no separate registry
object. Portals are RDF triples discoverable via SPARQL; membranes
are SHACL shapes; all state lives in the graph.

## Try in Browser

The example notebooks run in your browser via [JupyterLite](https://jupyterlite.readthedocs.io/).
No installation required — the library and its dependencies load
into a Pyodide kernel the first time you execute a cell.

<a href="jupyterlite/index.html">Open the in-browser lab</a>

What works: everything that doesn't need external services or
system extensions — `HolonicDataset`, portal traversal, membrane
validation via SHACL, projections, scope resolution, the projection
plugin system. What doesn't work: `FusekiBackend` (no HTTP in the
browser sandbox) and the `yfiles-jupyter-graphs` widgets from
notebook 11 (requires a Jupyter server extension). See the
`00_start_here.ipynb` notebook once you open the lab for the full
caveats.

## Quick Start

```python
from holonic import HolonicDataset

ds = HolonicDataset()  # rdflib backend, in-memory

ds.add_holon("urn:holon:source", "Source Data")
ds.add_interior("urn:holon:source", '''
    <urn:item:1> a <urn:type:Widget> ;
        <urn:prop:name> "Alpha" .
''')

print(ds.summary())
```

## Feature Tour

| Feature | Introduced | Entry point |
|---------|-----------|-------------|
| Four-graph holon model | 0.1.x | `add_holon`, `add_interior`, `add_boundary`, `add_projection`, `add_context` |
| Portal traversal + provenance | 0.2.x | `add_portal`, `traverse_portal`, `traverse`, `find_path` |
| Membrane validation (SHACL) | 0.2.x | `validate_membrane` |
| Projection utilities | 0.3.0 | `project_holon`, `apply_pipeline`, `project_holarchy` |
| Console-friendly dataclasses | 0.3.1 | `list_holons_summary`, `get_holon_detail`, `holon_neighborhood` |
| Graph-level metadata | 0.3.3 | `refresh_metadata`, `get_graph_metadata` |
| Ontological graph types | 0.3.4 | `cga:HolonicGraph` + `cga:graphRole`; `holonic-migrate-registry` CLI |
| Scope resolution | 0.3.4 | `resolve(predicate, from_holon, ...)` |
| Projection plugin system | 0.3.5 | `register_pipeline`, `run_projection`, `@projection_transform` |
| Protocol rename + ABC | 0.4.0 | `HolonicStore`, `AbstractHolonicStore` |

## Backends

- **RdflibBackend** — Default. Zero infrastructure, pure Python.
- **FusekiBackend** — Apache Jena Fuseki via SPARQL over HTTP.
- **Custom** — Implement the `HolonicStore` protocol, or inherit
  `AbstractHolonicStore` for optional-method defaults.

See [`backends`](./backends) for the full protocol surface.

## Migrating from 0.3.x

`GraphBackend` was renamed to `HolonicStore` in 0.4.0; the old name
remains as a deprecated alias through all of 0.4.x. Migration guide:
[`docs/MIGRATION.md`](../MIGRATION).

## Generating Documentation

```bash
pip install holonic[docs]
cd docs
sphinx-build -b html . _build/html
```

## Running the Example Notebooks

```bash
pixi run serve
```

This launches JupyterLab with the eleven example notebooks in `notebooks/` available. Notebooks are committed with outputs stripped; executing them locally populates output cells without affecting the committed state. Run `pixi run check-notebooks` before committing to confirm no outputs leaked in.

## Roadmap

See the project README for the headline roadmap. Full requirements tracked in [`SPEC`](../SPEC) under R9.11–R9.22.
