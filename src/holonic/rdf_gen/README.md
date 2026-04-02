# rdf_gen

Generate documents and code from RDF data using SPARQL queries as data bindings and Jinja2 templates as output formatters. The entire generation pipeline — templates, queries, bindings, and render specifications — can be described in RDF, making it as queryable and auditable as the data it operates on.

## The Value Proposition

RDF serves as a flexible canonical intermediate when integrating information from multiple sources. A SysML v2 model, a requirements database, and a simulation tool each produce data in different formats. Translated to RDF, that data participates in a single graph where SPARQL queries can cross-cut all sources simultaneously.

`rdf_gen` completes the pipeline: once data is in RDF, this library generates documents, reports, and code from it. The generation itself is described in RDF (as `gen:RenderSpec` entities), so the question "what documents does this data produce?" is answerable by querying the graph.

```
Source 1 (SysML v2)  ─── adapter ──→ ┐
Source 2 (DOORS)     ─── adapter ──→ ├── RDF Graph ──→ rdf_gen ──→ Documents / Code
Source 3 (AFSIM)     ─── adapter ──→ ┘                             (markdown, docx,
                                                                     python, matlab)
```

Adding a new source means writing one adapter (source → RDF). Adding a new output format means writing one template. The N×M integration problem becomes N+M.

## Installation

```bash
pip install rdflib pyshacl jinja2

# Optional: docx output
pip install python-docx
```

## Quick Start

### Minimal Example

```python
from rdf_gen import RenderEngine

engine = RenderEngine()

# Load domain data as TTL
engine.load_data('''
    @prefix eng: <urn:eng:> .
    <urn:eng:block:motor> a eng:Block ;
        rdfs:label "Electric Motor" ;
        eng:power 150 ;
        eng:unit "kW" .
''')

# Render with an inline template and a SPARQL query
result = engine.render_template(
    template_str="""
# Component Report
{% for item in components %}
- **{{ item.label }}**: {{ item.power }} {{ item.unit }}
{% endfor %}
    """,
    queries={
        "components": """
            PREFIX eng: <urn:eng:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?label ?power ?unit
            WHERE {
                ?b a eng:Block .
                ?b rdfs:label ?label .
                ?b eng:power ?power .
                OPTIONAL { ?b eng:unit ?unit }
            }
        """,
    },
)
print(result)
```

### Graph-Driven Specification

The template, bindings, and render spec can all live in RDF:

```python
engine.load_data(r'''
    <urn:gen:tmpl:report> a gen:Template ;
        gen:outputFormat "markdown" ;
        gen:templateBody """# {{ title }}
{% for item in items %}
- {{ item.label }}: {{ item.value }}
{% endfor %}""" .

    <urn:gen:spec:report> a gen:RenderSpec ;
        gen:title "My Report" ;
        gen:usesTemplate <urn:gen:tmpl:report> ;
        gen:hasBinding <urn:gen:bind:items>, <urn:gen:bind:title> .

    <urn:gen:bind:title> a gen:DataBinding ;
        gen:variableName "title" ;
        gen:resultType "scalar" ;
        gen:sparqlQuery """
            SELECT ?title WHERE {
                <urn:gen:spec:report> gen:title ?title .
            }
        """ .

    <urn:gen:bind:items> a gen:DataBinding ;
        gen:variableName "items" ;
        gen:resultType "list" ;
        gen:sparqlQuery """
            PREFIX eng: <urn:eng:>
            PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
            SELECT ?label ?value WHERE {
                ?b a eng:Block .
                ?b rdfs:label ?label .
                ?b eng:power ?value .
            }
        """ .
''')

content = engine.render("urn:gen:spec:report")
```

## Architecture

### The Generation Ontology (`gen:`)

The `gen:` ontology describes four concepts:

**`gen:Template`** — A Jinja2 template, either inline (`gen:templateBody`) or in a file (`gen:templatePath`). Declares its output format and file extension.

**`gen:DataBinding`** — Maps a SPARQL query to a Jinja2 template variable. The query is executed against the data graph; results are formatted according to `gen:resultType` and passed to the template.

**`gen:RenderSpec`** — Binds a template to its data bindings and declares the output path. Executing a RenderSpec produces a document or code file.

**`gen:DataSource`** — Provenance: records which source systems contributed data to the graph.

### Data Flow

```
1. LOAD     Multiple sources → RDF (via adapters/loaders)
2. LOAD     RenderSpec + Template + Bindings → same RDF graph
3. DISCOVER Engine reads RenderSpec from graph via SPARQL
4. EXECUTE  Each DataBinding's SPARQL query runs against the graph
5. RENDER   Results injected into Jinja2 template
6. OUTPUT   Rendered content written to file (markdown, docx, python, etc.)
```

### Result Types

Each `gen:DataBinding` declares how its query results are formatted for the template:

| `gen:resultType` | Template Receives | Use When |
|---|---|---|
| `"scalar"` | Single Python value | Title, count, single value |
| `"list"` | `list[dict]` (one dict per row) | Tables, iteration |
| `"grouped"` | `dict[key, list[dict]]` (grouped by first column) | Nested structures (blocks with params) |
| `"graph"` | `rdflib.Graph` (from CONSTRUCT) | Sub-graph processing |

### Grouped Results Pattern

The `"grouped"` result type is essential for nested data like blocks with parameters. The SPARQL query returns flat rows; the engine groups them by the first column:

```sparql
SELECT ?block ?label ?paramName ?paramValue
WHERE {
    ?block a eng:Block .
    ?block rdfs:label ?label .
    ?param eng:belongsTo ?block .
    ?param rdfs:label ?paramName .
    ?param eng:paramValue ?paramValue .
}
```

In the template, this becomes:

```jinja2
{% for block_uri, rows in blocks.items() %}
## {{ rows[0].label }}
{% for row in rows %}
- {{ row.paramName }}: {{ row.paramValue }}
{% endfor %}
{% endfor %}
```

## Mock Adapters (Loaders)

The library includes mock adapters that simulate translating from common engineering formats to RDF. In production, these would read real APIs/files.

### SysML v2 → RDF

```python
from rdf_gen import sysml_to_ttl

ttl = sysml_to_ttl(blocks=[
    {
        "name": "ThermalMgmtSubsystem",
        "stereotype": "Block",
        "parameters": [
            {"name": "mass", "value": 142.3, "unit": "kg"},
            {"name": "power", "value": 2.8, "unit": "kW"},
        ],
        "ports": [
            {"name": "coolantInlet", "direction": "in", "type": "FlowPort"},
        ],
    },
])
engine.load_data(ttl)
```

### Requirements (DOORS) → RDF

```python
from rdf_gen import requirements_to_ttl

ttl = requirements_to_ttl(requirements=[
    {
        "id": "REQ-MASS-001",
        "title": "Mass Limit",
        "text": "Mass shall not exceed 150 kg.",
        "priority": "SHALL",
        "allocated_to": "urn:eng:block:thermalmgmtsubsystem",
    },
])
engine.load_data(ttl)
```

### Simulation Results → RDF

```python
from rdf_gen import simulation_results_to_ttl

ttl = simulation_results_to_ttl(results=[
    {
        "name": "Peak Temperature",
        "value": 72.1,
        "unit": "C",
        "status": "PASS",
        "margin": 12.9,
    },
], tool="AFSIM")
engine.load_data(ttl)
```

### Generic JSON → RDF

```python
from rdf_gen import json_to_ttl

ttl = json_to_ttl(
    data={"name": "Widget", "weight": 42, "color": "blue"},
    base_uri="urn:data:widget-1",
)
engine.load_data(ttl)
```

## Template Features

Templates are standard Jinja2 with two additional filters:

| Filter | Function |
|--------|----------|
| `shorten` | Extract the local name from a URI: `"urn:eng:block:motor"` → `"motor"` |
| `uri_local` | Alias for `shorten` |

### Built-in Template Variables

Every render receives these variables automatically:

| Variable | Content |
|----------|---------|
| `_title` | From `gen:title` on the RenderSpec |
| `_description` | From `gen:description` |
| `_spec_iri` | The RenderSpec's IRI |
| `_format` | The output format |
| `_sections` | Ordered sections (if `gen:hasSection` is used) |

## Examples

### Example 1: Multi-Source System Specification

Integrates SysML v2 blocks, DOORS requirements, and AFSIM simulation results into a single system specification document.

```bash
python examples/example_system_spec.py
# → output/vehicle_system_spec.md
```

Demonstrates: multi-source loading, graph-described RenderSpec, grouped results for nested block/parameter tables, traceability matrix, analysis results table.

### Example 2: Code Generation

Generates Python dataclasses and a MATLAB simulation script from the same RDF design model.

```bash
python examples/example_code_gen.py
# → output/thermal_model.py
# → output/thermal_analysis.m
```

Demonstrates: single source → multiple output formats, the `render_template()` quick API, template-driven code generation, requirement thresholds as MATLAB variables.

### Example 3: Fully Graph-Driven Generation

Data, template (inline), bindings, and render spec all in one TTL block. The engine reads the spec from the graph and executes it. No external files.

```bash
python examples/example_graph_spec.py
# → output/req_traceability.md
```

Demonstrates: the pure RDF-native pattern where the generation pipeline is as queryable as the data.

## API Reference

### `RenderEngine`

The core class. Maintains a single rdflib Graph containing both domain data and generation specs.

**Loading:**

| Method | Purpose |
|--------|---------|
| `load_data(ttl)` | Parse TTL string into the graph |
| `load_file(path)` | Parse a file into the graph |
| `load_spec(ttl)` | Alias for `load_data` (specs are data) |
| `load_graph(g)` | Merge an rdflib Graph |

**Rendering:**

| Method | Purpose |
|--------|---------|
| `render(spec_iri)` | Execute a RenderSpec from the graph |
| `render_all()` | Execute all RenderSpecs in the graph |
| `render_template(template_str, queries)` | Quick API: no RenderSpec needed |
| `list_specs()` | List all RenderSpecs in the graph |

### `load_ttl(ttl) → Graph`

Convenience function: parse a TTL string (with auto-prefixed header) into a standalone Graph.

### Query Functions

| Function | Purpose |
|----------|---------|
| `execute_select(graph, query, result_type)` | Run SPARQL SELECT, format results |
| `execute_construct(graph, query)` | Run SPARQL CONSTRUCT, return Graph |

### Mock Adapters

| Function | Source Format |
|----------|-------------|
| `sysml_to_ttl(blocks, package)` | SysML v2 blocks with parameters and ports |
| `requirements_to_ttl(requirements)` | Requirements with IDs, text, priority |
| `simulation_results_to_ttl(results)` | Simulation outputs with margins |
| `json_to_ttl(data, base_uri)` | Generic JSON to RDF conversion |

## Project Structure

```
rdf_gen/
├── rdf_gen/
│   ├── __init__.py          # Public API
│   ├── namespaces.py        # Namespace definitions
│   ├── engine.py            # RenderEngine (core)
│   ├── queries.py           # SPARQL execution helpers
│   ├── loaders.py           # Mock source → RDF adapters
│   ├── ontologies/
│   │   └── gen.ttl          # Generation ontology
│   └── shapes/
│       └── gen_shapes.ttl   # SHACL shapes for render specs
├── templates/
│   ├── system_spec.md.j2    # System specification document
│   ├── python_dataclass.py.j2  # Python code generation
│   └── matlab_script.m.j2  # MATLAB script generation
├── examples/
│   ├── example_system_spec.py   # Multi-source document
│   ├── example_code_gen.py      # Python + MATLAB from RDF
│   └── example_graph_spec.py    # Fully graph-driven generation
├── requirements.txt
└── README.md
```

## Design Decisions

**Why describe the generation pipeline in RDF?** Because then "what documents can be generated from this data?" is a SPARQL query, not a search through a filesystem. The RenderSpec, Template, and DataBindings are graph entities with IRIs that can be versioned, traced, and audited alongside the data they operate on.

**Why SPARQL as the data binding mechanism?** Because the data is already in RDF. SPARQL is the native query language. Writing a SPARQL SELECT to extract template variables is more precise and more maintainable than writing Python code to walk the graph. The queries are also storable in the graph as `gen:sparqlQuery` literals.

**Why TTL over programmatic graph construction?** TTL is readable, auditable, and close to how the data would appear in a triple store. When someone asks "what data was used to generate this document?", showing them TTL is more useful than showing them `graph.add()` calls.

**Why Jinja2?** It is the most widely used template engine in Python, supports inheritance, macros, filters, and produces any text format. The `shorten` filter handles URI-to-local-name conversion for readable output.

**Why mock adapters instead of real parsers?** The library focuses on the RDF → output pipeline. Real SysML v2 API clients, ReqIF parsers, and HDF5 readers are substantial projects in their own right. The mock adapters produce the same RDF structure a real adapter would, demonstrating the integration pattern without the dependency burden.
