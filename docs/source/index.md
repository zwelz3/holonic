# holonic — Graph-Native Holonic RDF Systems

```{toctree}
:maxdepth: 2
:caption: Contents

api
projections
backends
ontology
```

## Overview

`holonic` is a lightweight Python client for building holonic knowledge graphs.
A holon is an IRI whose associated named graphs exist in an RDF dataset.
The dataset IS the holarchy — no separate registry object.

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

## Backends

- **RdflibBackend** — Default. Zero infrastructure, pure Python.
- **FusekiBackend** — Apache Jena Fuseki via SPARQL over HTTP.
- **Custom** — Implement the `GraphBackend` protocol for any quad store.

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
