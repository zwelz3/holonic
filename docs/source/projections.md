# Projections

Projections transform RDF graph structures into simplified forms useful for visualization, LPG-style analysis, or downstream consumption.  They bridge the gap between the semantic richness of RDF named graphs and the operational needs of visualization tools, NetworkX pipelines, and JSON APIs.

## Two Modes

### Graph-to-Graph (CONSTRUCT)

Stays in RDF.  Expressed as SPARQL CONSTRUCT queries.  Results can be stored as named graphs in the holarchy, traversed by portals, and queried via SPARQL.  Use this mode when the output will be consumed by another RDF-aware system or when you want to store a simplified view inside the holarchy.

```python
from holonic.projections import build_construct, CONSTRUCT_STRIP_TYPES

# Build and execute a CONSTRUCT
query = build_construct(CONSTRUCT_STRIP_TYPES, graph_iri="urn:holon:x/interior")
result_graph = ds.construct(query)
```

### Graph-to-Structure (Pythonic)

Exits RDF into Python dicts, `ProjectedGraph` instances, or other structures.  Use this mode for the "last mile" to visualization, JSON export, or LPG tools like NetworkX.

```python
from holonic.projections import project_to_lpg

lpg = project_to_lpg(graph,
    collapse_types=True,
    collapse_literals=True,
    resolve_blanks=True,
    resolve_lists=True,
)
# lpg.nodes: dict[str, ProjectedNode]
# lpg.edges: list[ProjectedEdge]
# lpg.to_dict(): JSON-serializable
```

## What Gets Collapsed

### Type Collapse

`rdf:type` triples become a `types: list[str]` attribute on the node rather than edges to type nodes.  This is what every graph visualization tool wants — the type is metadata about the node, not a relationship to display.

```
# RDF:
ex:alice rdf:type ex:Person .

# LPG projection:
Node(iri="urn:ex:alice", types=["urn:ex:Person"], ...)
```

### Literal Collapse

Literal-valued triples become entries in the node's `attributes` dict.  Multi-valued properties accumulate into lists.

```
# RDF:
ex:alice ex:age 30 .
ex:alice ex:name "Alice" .

# LPG projection:
Node(iri="urn:ex:alice", attributes={"urn:ex:age": 30, "urn:ex:name": "Alice"})
```

### Blank Node Resolution

Blank nodes that serve as structured values (addresses, sensor suites, configurations) are inlined as nested dicts on their parent node.

```
# RDF:
ex:alice ex:address _:addr .
_:addr ex:city "Vancouver" .
_:addr ex:street "123 Main St" .

# LPG projection:
Node(iri="urn:ex:alice", attributes={
    "urn:ex:address": {"urn:ex:city": "Vancouver", "urn:ex:street": "123 Main St"}
})
```

### RDF List Resolution

`rdf:first`/`rdf:rest` chains are resolved into Python lists.

```
# RDF:
ex:alice ex:skills _:list .
_:list rdf:first "Python" ; rdf:rest _:l2 .
_:l2 rdf:first "SPARQL" ; rdf:rest rdf:nil .

# LPG projection:
Node(iri="urn:ex:alice", attributes={"urn:ex:skills": ["Python", "SPARQL"]})
```

### Reification Collapse

`rdf:Statement` instances are unfolded into direct edges.  Non-structural properties on the statement (confidence, source, timestamp) become edge attributes — the LPG representation of properties on edges.

```python
from holonic.projections import collapse_reification

lpg = collapse_reification(graph, preserve_metadata=True)
# Edge(source=alice, predicate=knows, target=bob,
#      attributes={"confidence": 0.92, "source": "survey-2026"})
```

## Built-in CONSTRUCT Templates

| Template | Description |
|----------|-------------|
| `CONSTRUCT_STRIP_TYPES` | Remove all `rdf:type` triples |
| `CONSTRUCT_OBJECT_PROPERTIES_ONLY` | Keep only IRI objects (topology) |
| `CONSTRUCT_DATA_PROPERTIES_ONLY` | Keep only literal objects |
| `CONSTRUCT_COLLAPSE_REIFICATION` | Unfold `rdf:Statement` to direct triples |
| `CONSTRUCT_LABELS_ONLY` | Extract `rdfs:label`, `skos:prefLabel`, `skos:altLabel` |
| `CONSTRUCT_SUBCLASS_TREE` | Extract `rdfs:subClassOf` hierarchy with labels |

All templates accept an optional `graph_iri` parameter for `GRAPH` scoping:

```python
q = build_construct(CONSTRUCT_STRIP_TYPES, graph_iri="urn:holon:x/interior")
```

## Projection Pipelines

Chain CONSTRUCT and Python transform steps into composable pipelines.  Fluent API.

```python
from holonic.projections import (
    ProjectionPipeline,
    CONSTRUCT_STRIP_TYPES,
    strip_blank_nodes,
    localize_predicates,
)

lpg = (
    ProjectionPipeline("viz-prep")
    .add_construct("strip_types", CONSTRUCT_STRIP_TYPES)
    .add_transform("strip_blanks", strip_blank_nodes)
    .add_transform("localize", localize_predicates)
    .apply_to_lpg(source_graph)
)
```

Steps execute sequentially.  Each step receives the output of the previous step.  `.apply()` returns the final `Graph`; `.apply_to_lpg()` converts the final graph to a `ProjectedGraph`.

## Client Integration

`HolonicDataset` provides three projection methods:

### `project_holon(holon_iri, store_as=..., **kwargs)`

Merges all of a holon's interior graphs and projects to LPG.  Optionally stores the result as a projection named graph (`cga:hasProjection`).

```python
lpg = ds.project_holon("urn:holon:air-picture",
    store_as="urn:holon:air-picture/projection/viz",
    collapse_types=True,
    resolve_blanks=True,
)
```

### `project_holarchy(**kwargs)`

Projects the holarchy structure itself — holons as nodes, portals and `cga:memberOf` as edges.  Useful for visualizing the topology of the holarchy.

```python
topo = ds.project_holarchy()
# topo.nodes: holons and portals
# topo.edges: membership and portal connections
```

### `apply_pipeline(holon_iri, pipeline, store_as=...)`

Applies a `ProjectionPipeline` to a holon's merged interiors.

```python
result_graph = ds.apply_pipeline(
    "urn:holon:sensor-fused",
    my_pipeline,
    store_as="urn:holon:sensor-fused/projection/filtered",
)
```

## Utility Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `extract_types()` | `Graph → dict[str, list[str]]` | IRI → type list mapping |
| `filter_by_class()` | `Graph, class_iri → Graph` | Keep only instances of a class |
| `strip_blank_nodes()` | `Graph → Graph` | Remove all blank-node triples |
| `localize_predicates()` | `Graph → Graph` | Replace full IRIs with local names |

## API Reference

```{eval-rst}
.. autofunction:: holonic.projections.project_to_lpg

.. autofunction:: holonic.projections.collapse_reification

.. autofunction:: holonic.projections.build_construct

.. autoclass:: holonic.projections.ProjectionPipeline
   :members:

.. autoclass:: holonic.projections.ProjectedGraph
   :members:

.. autoclass:: holonic.projections.ProjectedNode
   :members:

.. autoclass:: holonic.projections.ProjectedEdge
   :members:
```
