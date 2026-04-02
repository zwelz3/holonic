# CGA Ontology

The **Context-Graph Architecture (CGA) Ontology** is a lightweight OWL 2 RL
vocabulary that defines the structural concepts for holonic RDF systems.

## Files

| File | Description |
|------|-------------|
| `holonic/ontology/cga.ttl` | OWL/RDFS vocabulary — classes, properties, individuals |
| `holonic/ontology/cga-shapes.ttl` | SHACL shapes constraining valid holarchy registries |

## Key Classes

| Class | Description |
|-------|-------------|
| `cga:Holon` | Entity with four-layer named-graph structure |
| `cga:Portal` | Governed traversal mechanism between holons |
| `cga:TransformPortal` | Portal carrying a SPARQL CONSTRUCT query |
| `cga:LayerGraph` | A named graph serving as one layer of a holon |
| `cga:LayerRole` | Enumeration: Interior, Boundary, Projection, Context |

## Key Properties

| Property | Domain → Range | Description |
|----------|---------------|-------------|
| `cga:hasInterior` | Holon → (graph) | Associates interior named graph(s) |
| `cga:hasBoundary` | Holon → (graph) | Associates boundary named graph(s) |
| `cga:hasProjection` | Holon → (graph) | Associates projection named graph(s) |
| `cga:hasContext` | Holon → (graph) | Associates context named graph(s) |
| `cga:sourceHolon` | Portal → Holon | Traversal origin |
| `cga:targetHolon` | Portal → Holon | Traversal destination |
| `cga:constructQuery` | TransformPortal → string | SPARQL CONSTRUCT query |
| `cga:memberOf` | Holon → Holon | Holarchy containment |

## Namespace

```
@prefix cga: <urn:holonic:ontology:> .
```
