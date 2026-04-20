# INSTRUCTIONS — holonic library

This document describes the intent, architecture, and design
philosophy of the `holonic` Python package. It is written for any
agent or contributor who needs to understand why the library is
shaped the way it is before making changes to it.

Read the whole thing before touching code. The library encodes
specific theoretical commitments that are not obvious from the API
surface alone.

Companion documents:
- `SPEC.md` — the specl-validated specification (requirements,
  user stories, open questions). Start here when planning a feature.
- `SPEC-objections.md` — steelmanned arguments against the current
  design direction, with preliminary counters. Read when defending
  or challenging a design decision.
- `DECISIONS.md` — one entry per significant design decision, with
  rationale and alternatives considered. Read before touching any
  area whose history is dense.
- `MIGRATION.md` — per-release migration guide. Start here when
  bumping the holonic dependency in a downstream project.
- `CHANGELOG.md` — shipped releases, additive truth of what exists
  in each version.

---

## 1. What this library is

`holonic` is a pip-installable Python package that implements a
graph-native holonic system on top of RDF named graphs.

A holon is a self-contained unit that is simultaneously a whole
(with its own interior structure) and a part of a larger system.
The library lets you create holons, connect them through portals
(SPARQL CONSTRUCT-mediated data projections), validate their
boundaries via SHACL membranes, and record provenance of every
operation via PROV-O.

The library is NOT a graph database. It is a client-side
coordination layer that sits in front of any quad-aware graph store
(rdflib, Apache Jena Fuseki, Oxigraph, GraphDB) and provides the
holonic abstractions on top.

Primary downstream consumers: `holonic-console` (FastAPI + React
operator web app), `hnn-scaffold` (PyTorch Holonic Neural Network
reference), `specl` (RDF-native spec-driven development, which
also validates this library's own SPEC).

---

## 2. Theoretical foundations

Two intellectual sources inform the architecture. Both must be
understood to make changes that fit.

### 2.1 Cagel's four-graph holon model

Each holon has four named-graph layers:

| Layer      | Question                | Content                              |
|------------|-------------------------|--------------------------------------|
| Interior   | What is true inside?    | A-Box triples, domain data           |
| Boundary   | What is allowed?        | SHACL shapes, portal definitions     |
| Projection | What do outsiders see?  | External bindings, vocab alignments  |
| Context    | Where does this belong? | Provenance, temporal annotations     |

Layer roles are explicit in the CGA ontology:
- `cga:InteriorRole`, `cga:BoundaryRole`, `cga:ProjectionRole`,
  `cga:ContextRole` as `cga:LayerRole` individuals.
- Bridging properties `cga:hasInterior`, `cga:hasBoundary`,
  `cga:hasProjection`, `cga:hasContext` as sub-properties of
  `cga:hasLayer`.

A holon MAY have multiple named graphs in any one layer role (e.g.
`urn:holon:sensor-a/interior/radar` and
`urn:holon:sensor-a/interior/fusion`). Reads across a layer treat
the set as a union.

The holon's IRI threads through all four layers as both the
identity anchor and the subject in cross-layer declarations stored
in a registry/holarchy graph.

This four-layer structure is not negotiable. Every method on
`HolonicDataset` that creates, reads, or modifies a holon must
respect it. A need for a fifth layer is almost always a concern
that already belongs in one of the four.

### 2.2 RDF named graphs as hypergraphs

The thesis: RDF named graphs are hypergraphs, and recognizing
them as such subsumes the RDF-vs-LPG distinction. A named graph is
a set of triples whose IRI can be the subject of triples in other
named graphs. The graph IRI is a hyperedge connecting all its
triples.

Practical consequences:

- **Named graphs are first-class.** The library never flattens to
  a single default graph. Every triple belongs to a named graph,
  and the graph IRI carries meaning (holon identity, layer role).
- **SPARQL queries are always graph-aware.** SELECT and CONSTRUCT
  use `GRAPH <iri> { ... }` to scope access. Queries that do not
  specify a graph are a code smell.
- **The `GraphBackend` protocol is quad-native.** All CRUD ops
  take a `graph_iri` parameter. No default-graph operations.
- **Portals are hyperedge traversals.** A portal's CONSTRUCT reads
  from a source holon's interior and writes into a target's. The
  portal IRI itself, declared in a boundary graph, is the
  hyperedge connecting the two holons.

This framing is why the library uses rdflib's `Dataset` (quad
store) as the local backend rather than `Graph` (triple store).

---

## 3. Architecture (0.4.0 state)

### 3.1 Module map

```
src/holonic/
├── __init__.py            re-exports HolonicDataset, store protocol, model
│                          and console-model dataclasses, scope resolver,
│                          plugin system
├── client.py              HolonicDataset — the primary API surface
├── model.py               HolonInfo, PortalInfo, MembraneResult, AuditTrail,
│                          SurfaceReport, ValidationRecord, TraversalRecord,
│                          MembraneBreachError
├── console_model.py       HolonSummary, HolonDetail, ClassInstanceCount,
│                          NeighborhoodNode/Edge/Graph, PortalSummary/Detail,
│                          GraphMetadata (0.3.3),
│                          ProjectionPipelineSpec/Step/Summary (0.3.5)
├── sparql.py              SPARQL templates as named string constants
├── projections.py         CONSTRUCT_STRIP_TYPES, project_to_lpg,
│                          ProjectionPipeline, first-party transforms
│                          (strip_blank_nodes, localize_predicates,
│                          collapse_reification) — all registered via
│                          @projection_transform
├── plugins.py             (0.3.5) entry-point discovery for projection
│                          transforms; @projection_transform decorator;
│                          TransformNotFoundError; host_metadata helper
├── scope.py               (0.3.4) ScopeResolver; HasClassInInterior,
│                          CustomSPARQL predicates; ResolveMatch/Order types
├── _metadata.py           (0.3.3) MetadataRefresher with native-dispatch hook
│                          (0.4.0) via hasattr(store, 'refresh_graph_metadata')
├── backends/
│   ├── store.py           (0.4.0) HolonicStore Protocol + AbstractHolonicStore ABC
│   ├── protocol.py        (0.4.0) deprecation shim re-exporting as GraphBackend
│   ├── __init__.py        exports HolonicStore, AbstractHolonicStore, RdflibBackend
│   ├── rdflib_backend.py  in-memory rdflib.Dataset backend (inherits ABC)
│   ├── fuseki_backend.py  Apache Jena Fuseki HTTP backend (inherits ABC)
│   └── _fuseki_client.py  low-level HTTP helpers
├── cli/
│   └── migrate_registry.py  (0.3.4) holonic-migrate-registry CLI for
│                             backfilling graph-type declarations
├── ontology/
│   ├── cga.ttl            CGA ontology (9 sections: holons, portals, layers,
│   │                      governance, + 0.3.3 graph-level metadata,
│   │                      + 0.3.4 graph type vocabulary,
│   │                      + 0.3.5 projection pipeline vocabulary)
│   └── cga-shapes.ttl     SHACL shapes (membrane validation scaffolding)
├── viz/
│   ├── graph_builder.py   build visualization-ready graph structures
│   ├── formatters.py      text/table formatters
│   ├── provenance.py      provenance visualization helpers
│   ├── styles.py          color/shape palettes
│   └── widgets.py         ipywidgets composite displays
└── test/                  pytest suite (all run against RdflibBackend;
                           Fuseki-specific tests use @pytest.mark.fuseki)
```

### 3.2 The `HolonicStore` protocol and `AbstractHolonicStore` ABC

```python
# Mandatory surface (unchanged from 0.3.x GraphBackend)
@runtime_checkable
class HolonicStore(Protocol):
    # Named-graph CRUD
    def graph_exists(self, graph_iri: str) -> bool: ...
    def get_graph(self, graph_iri: str) -> Graph: ...
    def put_graph(self, graph_iri: str, g: Graph) -> None: ...
    def post_graph(self, graph_iri: str, g: Graph) -> None: ...
    def delete_graph(self, graph_iri: str) -> None: ...
    def parse_into(self, graph_iri: str, data: str,
                   format: str = "turtle") -> None: ...
    # SPARQL
    def query(self, sparql: str, **bindings) -> list[dict]: ...
    def construct(self, sparql: str, **bindings) -> Graph: ...
    def ask(self, sparql: str, **bindings) -> bool: ...
    def update(self, sparql: str) -> None: ...
    # Utility
    def list_named_graphs(self) -> list[str]: ...

# ABC — recommended base class. Gets @abstractmethod enforcement on
# mandatory methods + hook point for optional-method defaults.
class AbstractHolonicStore(ABC):
    @abstractmethod
    def graph_exists(self, graph_iri: str) -> bool: ...
    # ... (same mandatory surface, abstract)
```

Extension: either inherit `AbstractHolonicStore` (recommended) or
duck-type the protocol, and pass the instance to
`HolonicDataset(backend=...)`. The rest of the library works
unchanged.

**Optional surface (0.4.0).** One method: `refresh_graph_metadata(
graph_iri, registry_iri)`. Backends implementing it natively get a
fast path; `MetadataRefresher` discovers the method via `hasattr`
and falls back to generic Python otherwise. The optional surface
grows additively through 0.4.x.

**`GraphBackend` deprecated alias** kept through all of 0.4.x. See
`MIGRATION.md`. Removal scheduled for 0.5.0 per SPEC R9.18.

Design constraints (unchanged):
- **Return types use `rdflib.Graph`** for CONSTRUCT and graph-fetch.
- **No async.** The protocol is synchronous. Async consumers wrap
  in `asyncio.to_thread()`. An async variant, if added, is a
  separate protocol, not a replacement.
- **SPARQL is strings.** Queries pass as raw SPARQL, not an AST.
  Templates live in `sparql.py` as named constants.

### 3.3 `HolonicDataset` — the primary API

Foundational (0.2.x / pre-0.3.1):
- `add_holon`, `add_interior`, `add_boundary`, `add_projection`,
  `add_context`, `list_holons`, `get_holon`
- `add_portal`, `find_portals_from`, `find_portals_to`,
  `find_portal`, `find_path`
- `traverse_portal`, `traverse` (composed discovery + validation +
  provenance)
- `validate_membrane`, `record_traversal`, `record_validation`
- `collect_audit_trail`, `materialize_rdfs`
- `query`, `construct`, `update`
- `project_holon`, `project_holarchy`, `apply_pipeline`
- `summary`, `compute_depth`

Added in 0.3.1 (console-shaped):
- `list_holons_summary()` — single-query lightweight listing
- `get_holon_detail(iri)` — full descriptor + interior triple count
- `holon_interior_classes(iri)` — `(class, count)` pairs
- `holon_neighborhood(iri, depth=1)` — BFS subgraph, graphology
  shape via `NeighborhoodGraph.to_graphology()`
- `list_portals()`, `get_portal(iri)` — flat portal browsing
- `portal_traversal_history(iri, limit=50)` — portal-scoped
  `prov:Activity` records

Added in 0.3.3 (graph-level metadata):
- `refresh_metadata(holon_iri)`, `refresh_all_metadata()`,
  `refresh_graph_metadata(graph_iri)` — explicit refresh surface
- `get_graph_metadata(graph_iri)` — returns `GraphMetadata`
- Constructor kwarg `metadata_updates="eager"|"off"`
- `get_holon_detail` extended with `layer_metadata` dict and
  `holon_last_modified`

Added in 0.3.4 (scope resolution + typed graphs):
- `resolve(predicate, from_holon, *, max_depth=3, order="network",
  limit=50)` — BFS walk with decreasing-priority matching
- Eager graph-type declaration on registration; backfill via
  `holonic-migrate-registry` CLI
- Registry self-typed as `cga:RegistryRole`

Added in 0.3.5 (projection plugin system):
- `register_pipeline(spec)`, `register_pipeline_ttl(ttl)` —
  register a persistent pipeline in the registry
- `attach_pipeline(holon_iri, spec_iri)`
- `list_pipelines(holon_iri)`, `get_pipeline(spec_iri)` —
  console-shaped query surface
- `run_projection(holon_iri, spec_iri, *, store_as=None,
  agent_iri=None)` — execute and record `prov:Activity` with loose
  version + host metadata

Added in 0.4.0 (protocol rename):
- No new methods. `backend` parameter type annotation is
  `HolonicStore`. Constructor kwarg renamed `registry_graph` →
  `registry_iri` (old name aliased through 0.4.x).

### 3.4 SPARQL query patterns

All SPARQL lives in `sparql.py` as named string constants. Never
build SPARQL by string concatenation at call sites. Naming
convention: `VERB_NOUN` (e.g. `COLLECT_HOLONS`,
`INSERT_TRAVERSAL_RECORD`, `PORTAL_TRAVERSAL_HISTORY_TEMPLATE`).
All queries use explicit `GRAPH <iri> { ... }` clauses.

### 3.5 The CGA ontology

Ships as `cga.ttl` in `src/holonic/ontology/`. Organized into six
concern areas:

1. Structure — holons, layers, portals, holarchies
2. Typing — functional and lifecycle classification
3. Governance — authority, stewardship, classification
4. Process — binding holons to business processes
5. Operations — freshness, sizing, materialization
6. Lifecycle — split, merge, archive, supersession

Uses RDFS plus minimal OWL (class hierarchy, domain/range). No
OWL reasoning. SHACL shapes are per-holon (boundary graphs), not
part of the ontology file.

Note on derivation vocabulary: the ontology defines two distinct
derivation predicates that serve different purposes.
- `prov:wasDerivedFrom` — PROV-O event-level derivation between
  entities generated by a specific activity. Used by portal
  traversal to record that the target interior was derived from
  the source interior during a particular traversal.
- `cga:derivedFrom` — persistent holon-to-holon structural
  dependency independent of any activity. Used to declare that a
  holon's identity or purpose continues to depend on another.

Both coexist. Neither replaces the other. See the cga.ttl
definitions for full semantics.

---

## 4. Design decisions and their rationale

### 4.1 Graph-native, not object-native

The v0.2.1 rewrite removed Python-object class hierarchies and
replaced them with a graph-native architecture. `HolonInfo`,
`PortalInfo`, `MembraneResult`, and the `console_model`
dataclasses are lightweight returns from queries, not persistent
domain objects. The source of truth is the graph store.

### 4.2 SPARQL over Python iteration

Express operations as SPARQL when they benefit from the store's
indexes. Python is for logic that cannot be expressed in SPARQL
(Dijkstra path ranking, pipeline step sequencing, template
rendering).

### 4.3 Nested Turtle notation

All examples, documentation, and test fixtures use nested Turtle
with `;` and `,` shortcuts.

### 4.4 Minimal dependencies

Hard deps: rdflib, pyshacl, pydantic. Optional extras: jupyter
(notebooks), aiohttp (fuseki), owlrl (entailment), ipywidgets +
yfiles-jupyter-graphs (viz).

### 4.5 The `rdflib.Graph` return type is deliberate

Trade-off: hard dependency on rdflib in exchange for immediate
access to serialization, iteration, and SPARQL evaluation on every
returned graph.

### 4.6 No async in the core

Sync-only protocol. Async consumers wrap in `asyncio.to_thread()`.
Any future `AsyncGraphBackend` should be a separate protocol.

### 4.7 Spec-driven development via specl

The library's SPEC is RDF-native, SHACL-validated, and maturity-
scored via specl (`pixi run spec-score`). Changes that add or
modify requirements go through the SPEC first; implementation
follows. The `spec-translate`, `spec-validate`, `spec-score`, and
`spec-badge` tasks are wired into pixi; see § 7.2.

---

## 5. How to extend the library

### 5.1 Adding a new backend

Implement `GraphBackend`, add tests matching
`test_backend.py` scenarios. Do not modify the protocol unless
genuinely required.

### 5.2 Adding a new query

Constant in `sparql.py`, method in `client.py`, dataclass in
`model.py` or `console_model.py`, test in `test/test_client.py`
(or a new test file if scope warrants).

### 5.3 Adding a new visualization

Builder function in `viz/`. Returns data structures, not rendered
output.

### 5.4 Adding a new projection step

Function in `projections.py`. Takes `Graph`, returns `Graph`.
Composes into `ProjectionPipeline`s.

### 5.5 Adding to the ontology

RDFS class/property declarations only. No complex OWL axioms.
Update dependent SPARQL in `sparql.py`. Bump ontology version in
the Turtle file's metadata.

### 5.6 Adding a requirement to SPEC.md

Use the specl markdown format (see `SPEC.md`). Requirement IDs
follow `R<group>.<index>` under an `H2` group header. Run
`pixi run spec-validate` to check structural conformance; run
`pixi run spec-score` for the maturity number.

---

## 6. Downstream consumers

### 6.1 holonic-console

Operator web application (FastAPI + React). Depends on
`HolonicDataset` query methods and `GraphBackend` for constructing
backends from registered service URLs. Stage 2 is the functional
proof for the 0.3.1 console_model additions.

### 6.2 hnn-scaffold

PyTorch Holonic Neural Network. Does NOT import holonic directly
because PyTorch tensors and rdflib graphs are incompatible
substrates. A `holonic_bridge.py` in the hnn-scaffold repo
translates between them.

### 6.3 specl

RDF-native SHACL-validated spec-driven development. Used by this
library to validate its own `SPEC.md`. The two projects were
co-designed; changes to the CGA ontology or SHACL patterns may
affect specl, and changes to specl's spec shapes affect
how `SPEC.md` is scored.

---

## 7. Development workflow

### 7.1 Pixi environments

The repo uses pixi for environment + task orchestration.
Environments:
- `dev` — full development: lint, test, docs, lab, jlite, spec
- `py311`, `py312`, `py313` — Python-version matrix for CI

### 7.2 Pixi tasks

Lint:
- `pixi run lint-fix` — runs, in order, `clean-notebooks`,
  `fix-pyproject`, `fix-ssort`, `format-ruff`, `fix-ruff`. The
  notebook step runs first so any stray committed cell outputs are
  removed before Python formatters touch anything.
- `pixi run lint-check` — runs `check-pyproject`, `check-ssort`,
  `check-ruff`, `check-notebooks`. The notebook check fails if any
  `.ipynb` under `notebooks/` has committed cell outputs or
  execution counts. Notebook outputs should never be committed;
  they bloat diffs and leak data.

Spec (requires the `dev` environment with `deps-spec`):
- `pixi run spec-translate` — `docs/SPEC.md` -> `docs/SPEC.ttl`
- `pixi run spec-validate` — pyshacl with `--explain`
- `pixi run spec-score` — print maturity percentage
- `pixi run spec-badge` — write `build/spec-badge.svg`

Test:
- `pixi run test` — pytest against in-memory backend; no external
  services required.

Docs:
- `pixi run build_html_docs` — sphinx HTML docs in `build/docs/`

Notebooks:
- `pixi run serve` — run jupyterlab locally
- `pixi run build_jl` — build the JupyterLite static site

### 7.3 Embedding the spec-maturity badge in the README

After `pixi run spec-badge`, add this to README.md below the title:

```markdown
![Spec Maturity](./build/spec-badge.svg)
```

The badge is an SVG with the score as a percent, color-coded: red
< 50%, yellow 50-84%, green >= 85%. For a public badge, commit the
SVG to a path the README can reach (or publish it to GitHub Pages
and link by URL). Regenerate on every spec change as part of the
doc build.

### 7.4 Release process

- Version in `src/holonic/__init__.py` and `pyproject.toml`
- CI/CD via GitHub Actions with PyPI trusted publishing
- Tag: `vX.Y.Z`
- Changelog: maintain in `CHANGELOG.md`

Versioning: patch = bug fixes + new queries. Minor = new methods +
ontology extensions (backward compatible). Major = breaking
changes (avoid).

---

## 8. Shipped roadmap

The SPEC's R9 group tracks all evolution items. What's shipped
since 0.3.1:

### 0.3.2 — ontology clarification (no API change)

- `cga.ttl` clarifies the `cga:derivedFrom` vs `prov:wasDerivedFrom`
  distinction explicitly with `skos:definition` entries.
- Pixi tasks added: `clean-notebooks`, `check-notebooks`, plus the
  spec pipeline (`spec-translate`, `spec-validate`, `spec-score`,
  `spec-badge`).

### 0.3.3 — graph-level metadata in the registry

- `cga:tripleCount`, `cga:lastModified`, `cga:refreshedAt`,
  `cga:inGraph`, `cga:class`, `cga:count`, `cga:holonLastModified`
  added in ontology § 7.
- Reified `cga:ClassInstanceCount` records with stable IRIs
  `<graph>/inventory/<slug>-<hash>`.
- `MetadataRefresher` class in `_metadata.py`.
- Constructor kwarg `metadata_updates="eager"|"off"`; default eager.
- Public methods: `refresh_metadata()`, `refresh_all_metadata()`,
  `refresh_graph_metadata()`, `get_graph_metadata()`.
- `HolonDetail` extended with `layer_metadata` and
  `holon_last_modified`.

### 0.3.4 — ontological graph categories + scoped discovery

- `cga:HolonicGraph` class + `cga:graphRole` property in ontology § 8.
- Flat + role pattern (not subclasses): a named graph carries
  `a cga:HolonicGraph ; cga:graphRole cga:InteriorRole`.
- New `cga:RegistryRole` individual for the registry graph itself.
- Eager graph typing on registration + idempotent backfill CLI
  (`holonic-migrate-registry`).
- `HolonicDataset.resolve(predicate, from_holon, ...)` in new
  `holonic.scope` module.
- Two predicate classes: `HasClassInInterior(class_iri)` (uses
  0.3.3 class inventory) and `CustomSPARQL(ask_template)` (escape
  hatch). Three BFS orders: `network` (default),
  `reverse-network`, `containment`.

### 0.3.5 — projection plugin system

- RDF-modeled pipelines in registry: `cga:ProjectionPipelineSpec`
  carries an `rdf:List` of `cga:ProjectionPipelineStep` entries.
- Python transforms discovered via `importlib.metadata` entry-point
  group `holonic.projections`. First-party transforms dogfood the
  same path (`strip_blank_nodes`, `localize_predicates`,
  `collapse_reification` registered in `pyproject.toml`).
- `@projection_transform(name)` decorator for in-process
  registration (useful in tests and notebooks).
- Public methods: `register_pipeline()`, `attach_pipeline()`,
  `list_pipelines()`, `get_pipeline()`, `run_projection()`,
  `register_pipeline_ttl()`.
- `run_projection` records `prov:Activity` with loose version
  tracking (`cga:transformVersion`) and host metadata
  (`cga:runHost`, `cga:runPlatform`, `cga:runPythonVersion`,
  `cga:runHolonicVersion`).

### 0.4.0 — protocol rename (BREAKING)

- `GraphBackend` Protocol renamed `HolonicStore` in new
  `holonic.backends.store` module.
- `AbstractHolonicStore` ABC for backend authors wanting
  `@abstractmethod` enforcement + future optional-method defaults.
- First-party backends (`RdflibBackend`, `FusekiBackend`) inherit
  the ABC.
- Minimal optional surface: `refresh_graph_metadata(graph_iri,
  registry_iri)`. Library dispatches via `hasattr` check.
- Deprecation aliases kept through 0.4.x: `GraphBackend`,
  `registry_graph=` kwarg. Warnings suppressible via
  `HOLONIC_SILENCE_DEPRECATION=1`.
- **Hard break**: `FusekiBackend(url, dataset=name)` — `dataset`
  keyword-only.

### Remaining (see SPEC R9.11–R9.22)

Tracked across the 0.5 → 0.7+ iterations with themes set in the
README roadmap:

- **0.5.0** — breaking cleanup with soft landing: R9.18 removals +
  R9.11 generators + R9.15 projection migration pass.
- **0.5.x** — protocol surface growth (additive): R9.17 native
  hooks, R9.12 lazy metadata mode, R9.16 per-step pipeline
  arguments.
- **0.6.0** — scope and registry expansion: R9.13 aggregated
  membrane health, R9.14 additional scope predicates.
- **0.7.0+** — contingent on evidence: OQ7 federation, R2.5
  async protocol, OQ8 tick semantics, OQ9 DOM event propagation.

R9.19 shipped in 0.4.1: JupyterLite static build of
`notebooks/01`–`11` (minus 11 which requires local Jupyter for
yFiles) served at `docs/source/_static/jupyterlite/` by the
ReadTheDocs build pipeline.

R9.20–R9.22 shipped in 0.4.2: structural lifecycle completion.
`remove_holon(iri)` with cascading cleanup of layer graphs,
registry bindings, metadata records, and incident portals.
`remove_portal(portal_iri)` with targeted removal that preserves
the boundary graph and sibling portals. Extended `add_portal()`
supporting all CGA portal subtypes (`TransformPortal`,
`IconPortal`, `SealedPortal`) plus downstream subclasses via
optional `construct_query`, customizable `portal_type`, and
`extra_ttl` for additional predicates. Portal discovery queries
relaxed to match any portal subtype and deduplicated via
`SELECT DISTINCT`.

Each step ships a patch version, passes its own specl
validation, and updates `CHANGELOG.md`. The SPEC maturity badge
climbs as requirements gain acceptance criteria and verification
links.

---

## 9. Style and conventions

- Argument-front-loaded prose. No marketing language.
- SPARQL and Turtle over Python iteration.
- Nested Turtle in all examples and fixtures.
- Minimal dependencies; honest deferral of complexity.
- Complete deployable files, not patches.
- Test fixtures in Turtle.
- JSON canonical interchange; YAML editing convenience.
- Notebook outputs are never committed; use `pixi run
  clean-notebooks` or let `lint-fix` handle it.

---

## 10. Things NOT to do

- Do not introduce an ORM or active-record pattern for holons.
- Do not add async to `HolonicStore`. Use a separate protocol if
  async ever ships.
- Do not add rendering to the library. Produce data structures.
- Do not add web framework code. That belongs in holonic-console.
- Do not add heavyweight dependencies (pandas, numpy, torch).
  Notebooks may `!pip install` dev-only extras at the top.
- Do not flatten named graphs to a single default graph.
- Do not build SPARQL by string concatenation at call sites.
- Do not add Python classes mirroring the RDF type hierarchy.
- Do not commit notebook cell outputs or execution counts.
- Do not replace `cga:derivedFrom` with `prov:wasDerivedFrom` or
  vice versa. They model distinct concepts; both are required.
- Do not remove a deprecated alias early. The 0.4.x series keeps
  `GraphBackend`, `registry_graph` kwarg, and `ds.registry_graph`
  property. Removal is 0.5.0 (SPEC R9.18).
- Do not skip recording host metadata in projection-run provenance.
  `cga:runHost`, `cga:runPlatform`, `cga:runPythonVersion`, and
  `cga:runHolonicVersion` are part of the reproducibility contract.
- Do not add a new feature without a DECISIONS.md entry. One
  paragraph is enough; the point is that the rationale exists.
