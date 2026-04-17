# holonic — Graph-Native Holonic RDF Systems

```{toctree}
:maxdepth: 2
:caption: Contents

api
projections
backends
ontology
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

## Generating Notebooks

```bash
pip install holonic[notebooks]
jupytext --to notebook examples/01_holon_basics.py
```
