# CGA Ontology

The **Context-Graph Architecture (CGA) Ontology** is a lightweight OWL 2 RL
vocabulary that defines the structural concepts for holonic RDF systems.

## Files

| File | Description |
|------|-------------|
| `holonic/ontology/cga.ttl` | OWL/RDFS vocabulary — classes, properties, individuals |
| `holonic/ontology/cga-shapes.ttl` | SHACL shapes constraining valid holarchy registries |

## Organization (9 sections)

| Section | Topic | Added |
|---------|-------|-------|
| 1 | Structural classes (Holon, Portal, LayerGraph, LayerRole, MembraneHealth) | 0.2.x |
| 2 | Holon type taxonomy (DataHolon, AlignmentHolon, AgentHolon, ...) | 0.2.x |
| 3 | Governance (DataDomain, BusinessProcess, Capability, ...) | 0.2.x |
| 4 | Lifecycle (HolonStatus, HolonSplit, HolonMerge) | 0.2.x |
| 5 | Object properties (layer bindings, portal, authority, stewardship, ...) | 0.2.x |
| 6 | Datatype properties (holonDepth, classification, operational, ...) | 0.2.x |
| 7 | Graph-level metadata (ClassInstanceCount + per-graph properties) | 0.3.3 |
| 8 | Graph type vocabulary (HolonicGraph + graphRole) | 0.3.4 |
| 9 | Projection pipeline vocabulary (ProjectionPipelineSpec + steps) | 0.3.5 |

## Key Classes

| Class | Description |
|-------|-------------|
| `cga:Holon` | Entity with four-layer named-graph structure |
| `cga:Portal` | Governed traversal mechanism between holons |
| `cga:TransformPortal` | Portal carrying a SPARQL CONSTRUCT query (reshapes data during traversal) |
| `cga:IconPortal` | Portal declaring a referential relationship with no transformation (traversal returns an empty projection) |
| `cga:SealedPortal` | Portal whose traversal is currently blocked; IRI persists for discovery and future re-opening |
| `cga:LayerGraph` | A named graph serving as one layer of a holon |
| `cga:LayerRole` | Individual: Interior, Boundary, Projection, Context, Registry |
| `cga:HolonicGraph` | Umbrella class for typed graphs (0.3.4; superclass of LayerGraph) |
| `cga:ClassInstanceCount` | Reified per-graph class inventory record (0.3.3) |
| `cga:ProjectionPipelineSpec` | Named, ordered pipeline of projection steps (0.3.5) |
| `cga:ProjectionPipelineStep` | One step carrying transform name or CONSTRUCT (0.3.5) |

### Portal subtype semantics

The three portal subclasses differ in whether they carry a `cga:constructQuery` and what traversal means for each. SHACL shapes in `cga-shapes.ttl` enforce these invariants.

| Subclass | `cga:constructQuery` | Traversal behavior | Shape severity for misuse |
|----------|---------------------|--------------------|--------------------------|
| `cga:TransformPortal` | **required** (minCount 1, maxCount 1) | Executes CONSTRUCT against source; produces projection | Violation if missing |
| `cga:IconPortal` | **forbidden** (maxCount 0) | Returns empty projection; relationship is purely referential | Warning if present |
| `cga:SealedPortal` | **forbidden** (maxCount 0) | Traversal blocked entirely; any query would never fire | Warning if present |

Downstream extensions may declare subclasses of `cga:TransformPortal` that substitute a domain-specific transformation predicate (for example, a reference to a learned function) for `cga:constructQuery`. Such subclasses override the query requirement with their own SHACL shape; the ontology does not force every portal to carry a SPARQL query.

## Key Properties

### Layer bindings (0.2.x)

| Property | Domain → Range | Description |
|----------|---------------|-------------|
| `cga:hasInterior` | Holon → graph | Associates interior named graph(s) |
| `cga:hasBoundary` | Holon → graph | Associates boundary named graph(s) |
| `cga:hasProjection` | Holon → graph | Associates projection named graph(s) |
| `cga:hasContext` | Holon → graph | Associates context named graph(s) |

### Portal (0.2.x, refined 0.4.2)

| Property | Domain → Range | Description |
|----------|---------------|-------------|
| `cga:sourceHolon` | Portal → Holon | Traversal origin (all subtypes) |
| `cga:targetHolon` | Portal → Holon | Traversal destination (all subtypes) |
| `cga:constructQuery` | TransformPortal → string | SPARQL CONSTRUCT query (required for TransformPortal; forbidden on IconPortal and SealedPortal by SHACL shape) |
| `cga:memberOf` | Holon → Holon | Holarchy containment |

### Derivation (distinguished in 0.3.2)

| Property | Domain → Range | Description |
|----------|---------------|-------------|
| `cga:derivedFrom` | Holon → Holon | Persistent structural dependency |
| `prov:wasDerivedFrom` | Entity → Entity | Event-level derivation via PROV-O |

These are distinct concepts; both coexist. See `cga.ttl` § 5 for the
full skos:definition.

### Graph-level metadata (0.3.3)

| Property | Domain → Range | Description |
|----------|---------------|-------------|
| `cga:tripleCount` | LayerGraph → integer | Triple count at last modification |
| `cga:lastModified` | LayerGraph → dateTime | UTC timestamp of most recent write |
| `cga:refreshedAt` | (any) → dateTime | Last metadata refresh timestamp |
| `cga:inGraph` | ClassInstanceCount → LayerGraph | Graph this inventory record covers |
| `cga:class` | ClassInstanceCount → Class | rdf:type being counted |
| `cga:count` | ClassInstanceCount → integer | Number of instances |
| `cga:holonLastModified` | Holon → dateTime | Rolled-up max of layer lastModified |

### Graph typing (0.3.4)

| Property | Domain → Range | Description |
|----------|---------------|-------------|
| `cga:graphRole` | HolonicGraph → LayerRole | Role a graph plays; may be multi-valued |

### Projection pipelines (0.3.5)

| Property | Domain → Range | Description |
|----------|---------------|-------------|
| `cga:hasPipeline` | Holon → ProjectionPipelineSpec | Holon declares pipeline availability |
| `cga:hasStep` | ProjectionPipelineSpec → rdf:List | Ordered list of steps |
| `cga:stepName` | ProjectionPipelineStep → string | Human-readable label |
| `cga:transformName` | ProjectionPipelineStep → string | Entry-point-registered transform name |

### Projection-run provenance (0.3.5)

These attach to `prov:Activity` records produced by `run_projection()`.

| Property | Description |
|----------|-------------|
| `cga:transformVersion` | "pkg==version" for each transform used |
| `cga:runHost` | Hostname where the run executed |
| `cga:runPlatform` | OS + architecture string |
| `cga:runPythonVersion` | Python interpreter version |
| `cga:runHolonicVersion` | holonic library version |

## Namespace

```turtle
@prefix cga: <urn:holonic:ontology:> .
```

## Other namespaces used

```turtle
@prefix prov:    <http://www.w3.org/ns/prov#> .
@prefix sh:      <http://www.w3.org/ns/shacl#> .
@prefix owl:     <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix schema:  <https://schema.org/> .
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
```
