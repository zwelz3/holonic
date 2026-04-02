# holonic

![](./static/holonic_logo-sm.PNG)

A lightweight Python client for building holonic knowledge graphs (based on Cagel's four-graph holonic RDF model) backed by rdflib, Apache Jena Fuseki, or any SPARQL-compliant quad store.


## The Four-Graph Model

Every `Holon` has four (or more!) named graphs, each answering a distinct question:

| Layer          | Question                | RDF Mechanism                       | Constructed With                         |
| -------------- | ----------------------- | ----------------------------------- | ---------------------------------------- |
| **Interior**   | What is true inside?    | Named graph, A-Box triples          | `interior_ttl=` or `load_interior()`     |
| **Boundary**   | What is allowed?        | SHACL shapes, portal definitions    | `boundary_ttl=` or `load_boundary()`     |
| **Projection** | What do outsiders see?  | External bindings, translated vocab | `projection_ttl=` or `load_projection()` |
| **Context**    | Where does this belong? | Membership, temporal annotations    | `context_ttl=` or `load_context()`       |

The holon's IRI threads through all four layers as both the identity anchor and a subject in cross-layer triples.


## Design Principle

> The dataset IS the holarchy. Python methods are convenience, not architecture.

A holon is not a Python object containing four `rdflib.Graph` attributes. A holon is an **IRI** whose associated named graphs exist in an RDF dataset. Portals are RDF triples in boundary graphs, discoverable via SPARQL. Traversal runs CONSTRUCT queries against the dataset with `GRAPH` scoping. All state lives in the quad store.

## Install

```bash
pip install holonic                     # core (rdflib + pyshacl)
pip install holonic[fuseki]             # + Fuseki backend
pip install holonic[entailment]         # + RDFS materialization
pip install holonic[dev]                # all extras + tests + docs
```

> Conda-forge support coming soon!

## Dev Install and Serve Jupyter Notebooks

```bash
pixi run serve
```

## Quick Start
```python
from holonic import HolonicDataset

ds = HolonicDataset()  # rdflib in-memory backend

# Create a holon with multiple interior graphs
ds.add_holon("urn:holon:sensor-a", "Sensor A")
ds.add_interior("urn:holon:sensor-a", '''
    <urn:track:001> a <urn:type:Track> ;
        <urn:prop:lat> 34.05 ;
        <urn:prop:lon> -118.25 .
''', graph_iri="urn:holon:sensor-a/interior/radar")

ds.add_interior("urn:holon:sensor-a", '''
    <urn:track:001> <urn:prop:confidence> 0.92 .
''', graph_iri="urn:holon:sensor-a/interior/fusion")

# Query across all interiors
rows = ds.query('''
    SELECT ?track ?lat ?conf WHERE {
        GRAPH ?g1 { ?track <urn:prop:lat> ?lat }
        GRAPH ?g2 { ?track <urn:prop:confidence> ?conf }
    }
''')
```

## Backends

| Backend | Import | Infrastructure |
|---------|--------|----------------|
| `RdflibBackend` | `from holonic import RdflibBackend` | None (in-memory) |
| `FusekiBackend` | `from holonic.backends.fuseki_backend import FusekiBackend` | Fuseki server |
| Custom | Implement `GraphBackend` protocol | Any quad store |

```python
# Fuseki backend
from holonic.backends.fuseki_backend import FusekiBackend

ds = HolonicDataset(
    backend=FusekiBackend("http://localhost:3030", "holarchy")
)
```


## Key Concepts

### Holons Have Multiple Interior Graphs

A holon's interior is a *set* of named graphs, not a single graph:

```python
ds.add_interior(holon, ttl_a, graph_iri="urn:holon:x/interior/radar")
ds.add_interior(holon, ttl_b, graph_iri="urn:holon:x/interior/eo-ir")
```

### Portals Are RDF, Discovered via SPARQL

```python
# Register (writes triples into boundary graph)
ds.add_portal("urn:portal:a-to-b", source, target, construct_query)

# Discover (SPARQL query, not Python iteration)
portals = ds.find_portals_from("urn:holon:source")
path = ds.find_path("urn:holon:a", "urn:holon:c")  # multi-hop BFS
```

### Traversal Runs CONSTRUCT Against the Dataset

```python
# Low-level: execute a portal's CONSTRUCT
projected = ds.traverse_portal("urn:portal:a-to-b",
                                inject_into="urn:holon:b/interior")

# High-level: find portal → traverse → validate → record provenance
projected, membrane = ds.traverse(
    "urn:holon:source", "urn:holon:target",
    validate=True,
    agent_iri="urn:agent:pipeline",
)
```

### Membrane Validation Operates on Graph Unions

```python
result = ds.validate_membrane("urn:holon:target")
# Validates union of all cga:hasInterior graphs
# against union of all cga:hasBoundary graphs
```

### Projections: RDF → Visualization

Two modes: **CONSTRUCT** (stays in RDF, storable in the holarchy) and **Pythonic** (exits RDF into dicts/LPG for visualization).

```python
from holonic import project_to_lpg, ProjectionPipeline, CONSTRUCT_STRIP_TYPES

# Full LPG projection — types, literals, blank nodes, lists all collapsed
lpg = project_to_lpg(graph,
    collapse_types=True,       # rdf:type → node.types list
    collapse_literals=True,    # literals → node.attributes dict
    resolve_blanks=True,       # blank nodes → nested dicts
    resolve_lists=True,        # rdf:first/rest → Python lists
)
lpg.to_dict()  # JSON-serializable

# Composable pipeline (CONSTRUCT + Python transforms)
lpg = (
    ProjectionPipeline("viz-prep")
    .add_construct("strip_types", CONSTRUCT_STRIP_TYPES)
    .add_transform("localize", localize_predicates)
    .apply_to_lpg(source_graph)
)

# Project a holon (merge interiors → LPG, store result)
lpg = ds.project_holon("urn:holon:air", store_as="urn:holon:air/projection/viz")

# Project the holarchy topology (holons as nodes, portals as edges)
topo = ds.project_holarchy()
```

## CGA Ontology

The package includes a lightweight OWL 2 RL vocabulary (`holonic/ontology/cga.ttl`) and SHACL shapes (`cga-shapes.ttl`) defining the structural concepts: `cga:Holon`, `cga:TransformPortal`, `cga:hasInterior`, `cga:hasBoundary`, `cga:constructQuery`, etc.

## Examples

| Example | Description |
|---------|-------------|
| `examples/01_holon_basics.py` | Holon creation, multi-interior, membrane validation |
| `examples/02_portal_traversal.py` | Portal discovery, multi-hop paths, provenance |
| `examples/03_gra_interop.py` | Cross-standard GRA message translation (OMS→FACE) |
| `examples/04_projections.py` | Type/literal/blank-node collapse, pipelines, holarchy projection |

```bash
# Run as scripts
python examples/01_holon_basics.py

# Or convert to notebooks
pip install jupytext
jupytext --to notebook examples/04_projections.py
```

## Documentation

```bash
pip install holonic[docs]
cd docs && sphinx-build -b html . _build/html
```

## Tests

```bash
pip install holonic[dev]
pytest
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    HolonicDataset                       │
│  (thin Python wrapper — SPARQL queries)                 │
├─────────────────────────────────────────────────────────┤
│                   GraphBackend Protocol                 │
│         graph_exists · get/put/post/delete_graph        │
│         query · construct · ask · update                │
├──────────────────┬──────────────────────────────────────┤
│  RdflibBackend   │  FusekiBackend   │  YourBackend      │
│  (rdflib.Dataset)│  (HTTP/SPARQL)   │  (protocol impl)  │
└──────────────────┴──────────────────┴───────────────────┘
```

## References

- Kurt Cagel, "The Living Graph: Holons and the Four-Graph Model," *The Ontologist*, March 2026
- Arthur Koestler, *The Ghost in the Machine*, 1967
- W3C SHACL Specification
- W3C PROV-O Ontology