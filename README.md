# holonic

![](./static/holonic_logo-sm.PNG)

A Python library for Cagel's four-graph holonic RDF model, implementing governed graph traversal with SPARQL CONSTRUCT translation, SHACL membrane validation, self-describing portal surfaces, and PROV-O provenance.

## Installation and Serve Jupyter Notebooks

```bash
pixi run serve
```

## Quick Start

```python
from holonic import Holon, TransformPortal, validate_membrane

# Build a holon with TTL-defined content
city = Holon(
    iri="urn:holon:city:vancouver",
    label="Vancouver",
    depth=2,
    interior_ttl='''
        @prefix geo: <urn:geo:> .
        <urn:city:vancouver> a geo:City ;
            rdfs:label "Vancouver" ;
            geo:population 675218 ;
            geo:latitude 49.2827 .
    ''',
    boundary_ttl='''
        @prefix geo: <urn:geo:> .
        <urn:shapes:CityShape> a sh:NodeShape ;
            sh:targetClass geo:City ;
            sh:property [
                sh:path rdfs:label ;
                sh:minCount 1 ;
                sh:severity sh:Violation
            ] .
    ''',
)

# Validate the interior against the boundary membrane
result = validate_membrane(city)
print(result.summary())
# Membrane [Vancouver]: INTACT
#   conforms: True
```

## The Four-Graph Model

Every `Holon` has four named graphs, each answering a distinct question:

| Layer          | Question                | RDF Mechanism                       | Constructed With                         |
| -------------- | ----------------------- | ----------------------------------- | ---------------------------------------- |
| **Interior**   | What is true inside?    | Named graph, A-Box triples          | `interior_ttl=` or `load_interior()`     |
| **Boundary**   | What is allowed?        | SHACL shapes, portal definitions    | `boundary_ttl=` or `load_boundary()`     |
| **Projection** | What do outsiders see?  | External bindings, translated vocab | `projection_ttl=` or `load_projection()` |
| **Context**    | Where does this belong? | Membership, temporal annotations    | `context_ttl=` or `load_context()`       |

The holon's IRI threads through all four layers as both the identity anchor and a subject in cross-layer triples.

### Layer Construction

All graph content is defined as Turtle strings. Standard prefixes (`rdf:`, `rdfs:`, `xsd:`, `sh:`, `cga:`, `prov:`, etc.) are auto-prepended. Never use `graph.add()` for domain data.

```python
holon.load_interior('''
    @prefix ex: <urn:ex:> .
    <urn:thing:1> a ex:Widget ;
        ex:weight 42 ;
        ex:color "blue" .
''')
```

### Identity Seeding

The constructor automatically seeds the interior with holon identity triples:

```turtle
<urn:holon:city:vancouver> a cga:Holon ;
    rdfs:label "Vancouver"^^xsd:string ;
    cga:holonDepth 2 ;
    cga:interiorGraph   <urn:holon:city:vancouver/interior> ;
    cga:boundaryGraph   <urn:holon:city:vancouver/boundary> ;
    cga:projectionGraph <urn:holon:city:vancouver/projection> ;
    cga:contextGraph    <urn:holon:city:vancouver/context> .
```

## Portals

Portals are boundary membrane objects that govern traversal between holons.

### Simple Portal (passthrough)

```python
from holonic import Portal

p = Portal(
    iri="urn:portal:a-to-b",
    source=holon_a,
    target=holon_b,
    label="A → B",
)

# Traverse: returns a copy of the input graph
result = p.traverse(holon_a.interior)
```

### TransformPortal (SPARQL CONSTRUCT translation)

The key mechanism for cross-vocabulary translation. The CONSTRUCT query reshapes triples from the source's schema into the target's expected form.

```python
from holonic import TransformPortal

portal = TransformPortal(
    iri="urn:portal:sysml-to-sim",
    source=sysml_holon,
    target=sim_holon,
    label="SysML → Simulation",
    construct_query='''
        PREFIX sysml: <urn:sysml:>
        PREFIX sim:   <urn:sim:>

        CONSTRUCT {
            ?block a sim:InputBlock .
            ?block rdfs:label ?name .
            ?block sim:inputParam ?param .
            ?param sim:paramValue ?val .
        }
        WHERE {
            ?block a sysml:Block .
            ?block sysml:name ?name .
            ?param sysml:memberOf ?block .
            ?param sysml:value ?val .
        }
    ''',
    validate_output=True,  # validate against target boundary
)

# Traverse: applies CONSTRUCT, validates output, returns projected graph
projected = portal.traverse(sysml_holon.interior)
```

If `validate_output=True` and the projected graph violates the target's SHACL shapes, a `MembraneBreachError` is raised.

### Portal Registration

Creating a portal automatically writes its definition as TTL into the source holon's boundary graph:

```turtle
<urn:portal:sysml-to-sim> a cga:TransformPortal ;
    rdfs:label "SysML → Simulation" ;
    cga:sourceHolon <urn:holon:tool:sysml> ;
    cga:targetHolon <urn:holon:tool:sim> ;
    cga:isTraversable true ;
    cga:transformSpec "PREFIX sysml: ..." .

<urn:holon:tool:sysml> cga:hasPortal <urn:portal:sysml-to-sim> .
```

### Sealed Portals

```python
sealed = Portal(
    iri="urn:portal:sealed",
    source=a, target=b,
    traversable=False,  # sealed — traverse() returns None
)
```

## Self-Describing Portal Surface

The most architecturally significant pattern in the library. A target holon's SHACL shapes are simultaneously a validation rulebook, an API contract, and a discovery surface.

### Discovering the Target's Surface

```python
from holonic import discover_target_shape, describe_surface

# Human-readable surface description
print(describe_surface(target_holon))
# Surface of 'Simulation Tool':
#   Target class: InputBlock (urn:sim:InputBlock)
#     label        REQUIRED   [string]
#     inputParam   REQUIRED
#     ...

# Structured discovery
shapes = discover_target_shape(target_holon)
for cls, props in shapes.items():
    for p in props:
        print(f"{p.path_local}: required={p.is_required}, type={p.datatype}")
```

### Generating CONSTRUCT from Surface

```python
from holonic import generate_construct_query

query = generate_construct_query(
    source_class="sysml:Block",
    target_class="sim:InputBlock",
    property_map={
        "sysml:name":  "rdfs:label",
        "sysml:value": "sim:paramValue",
        "sysml:unit":  "sim:paramUnit",
    },
    prefixes="PREFIX sysml: <urn:sysml:>\nPREFIX sim: <urn:sim:>",
)
```

### The Pattern

```
1. TARGET declares SHACL shapes     → "I accept these properties"
2. SOURCE queries the shapes         → discover_target_shape()
3. ENGINEER writes property map      → {source_prop: target_prop}
4. LIBRARY generates CONSTRUCT       → generate_construct_query()
5. PORTAL carries and executes it    → TransformPortal.traverse()
6. TARGET validates the output       → validate_membrane()
7. PROVENANCE records the operation  → ProvenanceTracker
```

## Membrane Validation

SHACL validation interpreted as holonic membrane health:

```python
from holonic import validate_membrane, MembraneHealth

result = validate_membrane(holon)
print(result.health)   # MembraneHealth.INTACT / WEAKENED / COMPROMISED
print(result.conforms)  # True / False
print(result.violations)  # list of violation messages
print(result.summary())  # formatted report
```

**Severity mapping:**

| SHACL Severity | Membrane Health | Meaning                             |
| -------------- | --------------- | ----------------------------------- |
| `sh:Violation` | `COMPROMISED`   | Membrane is genuinely breached      |
| `sh:Warning`   | `WEAKENED`      | Membrane is degraded but functional |
| `sh:Info`      | (advisory)      | No structural concern               |

## Provenance (PROV-O)

Every operation on a holon can be recorded as a PROV-O Activity in the target's context graph.

```python
from holonic import ProvenanceTracker

prov = ProvenanceTracker(
    agent_iri="urn:agent:my-pipeline",
    agent_label="Translation Pipeline v1",
)

# Record a portal traversal
prov.record_traversal(
    portal_iri="urn:portal:sysml-to-sim",
    source=sysml_holon,
    target=sim_holon,
    notes="Design parameters translated for thermal analysis.",
)

# Record a validation
prov.record_validation(
    holon=sim_holon,
    conforms=True,
    health="intact",
)
```

This writes PROV-O triples into the target's context graph:

```turtle
<urn:prov:traversal:abc123> a prov:Activity ;
    rdfs:label "Portal traversal: SysML → Simulation" ;
    prov:startedAtTime "2026-03-30T..." ;
    prov:wasAssociatedWith <urn:agent:my-pipeline> ;
    prov:used <urn:holon:tool:sysml/interior> ;
    prov:generated <urn:holon:tool:sim/interior> .

<urn:holon:tool:sim/interior>
    prov:wasGeneratedBy <urn:prov:traversal:abc123> ;
    prov:wasDerivedFrom <urn:holon:tool:sysml/interior> .
```

## Visualization (`holonic.viz`)

Interactive graph visualization using yFiles Jupyter Graphs.

```bash
pip install yfiles-jupyter-graphs ipywidgets
```

### HolonViz — Single Holon

Renders a holon's four named graphs as nested groups with layer colour coding.

```python
from holonic.viz import HolonViz

viz = HolonViz(my_holon, layers=["interior", "boundary"])
w = viz.show()           # returns yFiles GraphWidget
viz.show_with_controls() # adds ipywidgets layer/layout toggles
```

| Layer      | Colour | Shape           |
| ---------- | ------ | --------------- |
| Interior   | Blue   | Round Rectangle |
| Boundary   | Purple | Hexagon         |
| Projection | Green  | Pill            |
| Context    | Amber  | Octagon         |
| Portal     | Red    | Triangle        |
| Literal    | Grey   | Ellipse         |

### HolarchyViz — Full Holarchy

Holons as parent groups, portals as cross-group edges. Toggle between collapsed (atomic holon nodes) and expanded (interior triples visible) views.

```python
from holonic.viz import HolarchyViz

# Collapsed: holons as single nodes, portals as edges
viz = HolarchyViz(my_holarchy, show_internals=False)
w = viz.show()

# Expanded: layers visible inside each holon
viz = HolarchyViz(my_holarchy, show_internals=True, layers=["interior", "boundary"])
w = viz.show()

# With interactive controls
viz.show_with_controls()
```

### SPARQLExplorer — Interactive Query Widget

Executes SPARQL CONSTRUCT queries against a local rdflib graph and renders results in a linked yFiles widget. Includes namespace management and built-in projection presets.

```python
from holonic.viz import SPARQLExplorer

explorer = SPARQLExplorer(
    graph=my_holarchy.merged_all(),
    namespaces={"geo": "urn:geo:", "muni": "urn:municipal:"},
)
explorer.show()  # full interactive widget with dropdown presets

# Programmatic use
result = explorer.execute("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
w = explorer.visualise_result(result)
```

**Built-in projection presets:**

| Preset             | Description                                    |
| ------------------ | ---------------------------------------------- |
| All Triples        | Every triple (caution: may be large)           |
| Interior Only      | A-Box data without SHACL or structural triples |
| SHACL Shapes       | Boundary membrane shapes and properties        |
| Portal Network     | All portals with source/target holons          |
| Holarchy Structure | Holons and nesting relationships               |
| Provenance Trail   | PROV-O activities with agents and derivations  |
| External Bindings  | cga:bindsTo and skos:exactMatch links          |
| Type Hierarchy     | rdf:type and rdfs:subClassOf relationships     |

Custom projections are entered in the monospace textarea and executed on button click.

## Project Structure

```
holonic/
├── holonic/
│   ├── __init__.py          # Public API
│   ├── namespaces.py        # CGA namespace, TTL prefix block
│   ├── holon.py             # Core Holon (four named graphs)
│   ├── portal.py            # Portal, TransformPortal, MembraneBreachError
│   ├── membrane.py          # SHACL validation as membrane health
│   ├── provenance.py        # PROV-O activity recording
│   ├── surface.py           # Self-describing portal surface discovery
│   ├── holarchy.py          # Holarchy manager
│   └── viz/
│       ├── __init__.py      # Viz subpackage
│       ├── styles.py        # Colour palettes, shapes, scales
│       ├── graph_builder.py # Holon/Holarchy → yFiles nodes/edges
│       ├── projections.py   # Built-in SPARQL projection presets
│       └── widgets.py       # HolonViz, HolarchyViz, SPARQLExplorer
├── notebooks/*   					 # Jupyter notebook examples
├── pixi.toml  							 # pixi.sh build process
└── README.md
```

## References

- Kurt Cagel, "The Living Graph: Holons and the Four-Graph Model," *The Ontologist*, March 2026
- Arthur Koestler, *The Ghost in the Machine*, 1967
- W3C SHACL Specification
- W3C PROV-O Ontology