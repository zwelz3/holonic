# DECISIONS — holonic library

This document records architectural decisions and their rationale.
It complements `SPEC.md` (the normative requirements) by capturing
the reasoning behind implementation choices that are not themselves
requirements.

Decisions are grouped by release. Within a release, they appear in
roughly the order they were made.

---

## 0.3.3 — Graph-level metadata in the registry

### D-0.3.3-1 — The registry is a single designated named graph

**Decision:** All graph-level metadata, graph typing, and cross-
holon structural declarations live in a single named graph at
`urn:holarchy:registry`.

**Alternatives considered:**

- **Per-holon context graphs.** Each holon's metadata travels with
  the holon. No central registry; cross-holon queries require a
  `UNION` over context graphs.
- **Implicit registry** (the graph the library happens to write
  holon declarations to). No migration needed but "the registry"
  remains undefined.

**Rationale:** A designated registry is a prerequisite for the
0.3.4+ scoped discovery work (R9.3) and the R9.1 ontological graph
categories. Per-holon context is a valid alternative for small
single-tenant deployments but makes cross-holon metadata queries
either slow (fan-out) or impossible (federation). The implicit-
registry option kicks the design decision downstream without
avoiding it.

**Migration:** The library now writes new holon and portal
declarations directly to `urn:holarchy:registry`. Existing
deployments with declarations scattered across other graphs run a
one-shot CLI tool (`holonic-migrate-registry`) in a maintenance
window. The migration is idempotent and reversible (the tool
records what it moved in an activity on the `urn:holarchy:registry`
context).

**Implications for downstream:**

- `holonic-console` service registrations and service catalog live
  outside `urn:holarchy:registry` — the console's service registry
  is a different concern (which graph stores to query) than the
  holonic registry (what's in those stores). Do not conflate.
- Multi-tenant or federated deployments will eventually need
  multiple registries. The IRI pattern `urn:holarchy:<name>/registry`
  is reserved for that; a flat `urn:holarchy:registry` is the
  single-tenant default.
- Deployments that already keep their holon declarations in a
  non-default graph can alias via configuration
  (`HolonicDataset(registry_graph_iri="custom:iri")`) — the
  default lands on `urn:holarchy:registry`.

**Open for the future:**

- Federation of multiple registries (R9 item, deferred beyond 0.3.x).
- Registry-as-holon recursion (SPEC.md Open Question 1). The
  registry IRI is hardcoded now; becoming a holon is a later
  decision.

### D-0.3.3-2 — Two metadata update modes only

**Decision:** `HolonicDataset(metadata_updates: Literal["eager", "off"] = "eager")`.

**Alternatives considered:** Adding a `"lazy"` mode with deferred
writes and a `flush_metadata()` call.

**Rationale:** Two modes are significantly easier to reason about
than three. Eager covers interactive use (console, notebooks). Off
covers batch pipelines where the caller manages metadata explicitly
via `refresh_metadata()`. Lazy mode is a third semantic regime
(dirty tracking, flush semantics, race conditions under concurrent
reads) that deserves its own design pass, not a rushed inclusion.

If lazy mode emerges as necessary in 0.3.4+, the existing API
accommodates it additively (`"lazy"` added to the Literal, no
breaking change to existing callers).

### D-0.3.3-3 — Class inventory uses reified `ClassInstanceCount` resources

**Decision:** Class inventory is recorded as:

```turtle
<urn:holon:foo/interior/radar/inventory/ex-TrackMessage>
    a cga:ClassInstanceCount ;
    cga:inGraph     <urn:holon:foo/interior/radar> ;
    cga:class       <urn:vocab:TrackMessage> ;
    cga:count       1247 ;
    cga:refreshedAt "2026-04-16T18:30:00.123456Z"^^xsd:dateTime .
```

**Alternatives considered:**

- **Direct predicate.** `?g cga:containsType ?cls` (reuses existing
  property). Simpler, but loses counts.
- **Blank-node inventory.** `?g cga:typeInventory [ cga:class ?c ; cga:instanceCount N ]`.
  Captures counts but blank nodes are awkward to update in SPARQL.

**Rationale:** Reified records with stable IRIs are addressable and
updatable. SPARQL UPDATE on a specific count becomes a one-pattern
DELETE/INSERT. The IRI encodes the (graph, class) pair so refresh
is idempotent. The `console_model.ClassInstanceCount` dataclass
from 0.3.1 maps directly to these records.

**IRI convention:** `<graph-iri>/inventory/<slugified-class-iri>`
where slug is a URL-safe encoding of the class local name (with a
hash suffix for disambiguation when local names collide).

### D-0.3.3-4 — Metadata lives at both per-graph and per-holon levels

**Decision:** Per-graph metadata (`cga:tripleCount`, `cga:lastModified`,
`cga:classInstanceCount`) is the source of truth. Per-holon rollups
(existing `cga:interiorTripleCount`, new `cga:holonLastModified`,
rolled-up `cga:containsType`) are derived on the same write.

**Rationale:** The console and other consumers frequently ask both
"how many triples in this interior graph?" and "how many total
triples across this holon's interior?" Maintaining both costs one
extra rollup query per metadata update and saves every reader from
summing themselves. The existing `cga:interiorTripleCount` on
`cga:Holon` stays in place; we are extending, not replacing.

### D-0.3.3-5 — Update triggers

**Metadata refreshes automatically on these library-mediated writes:**

- `traverse_portal()`, `traverse()` — target interior graph(s)
- `add_interior()`, `add_boundary()`, `add_projection()`, `add_context()`
- `apply_pipeline()` with `store_as=...`
- `project_holon(store_as=...)` — the projection graph AND the
  source interior graphs (projection counts as a read of the
  sources, but their `lastModified` is not affected; their
  class inventory is re-verified)

**Metadata does NOT refresh on:**

- Direct `backend.put_graph()` / `backend.post_graph()` / `backend.update()`
  calls — the library cannot intercept these. Document as a known
  limit. Provide `HolonicDataset.refresh_metadata(holon_iri)` and
  `refresh_all_metadata()` as escape hatches.

**Membrane health is NOT registry metadata.** Current membrane
health remains in the holon's context graph as a `prov:Activity`
payload, as it does today. Aggregating health into the registry is
a separate future decision — see D-0.3.3-7 below.

### D-0.3.3-6 — API additions

Three new methods and one new dataclass:

- `HolonicDataset.refresh_metadata(holon_iri: str) -> None`
- `HolonicDataset.refresh_all_metadata() -> None`
- `HolonicDataset.get_graph_metadata(graph_iri: str) -> GraphMetadata | None`
- `holonic.console_model.GraphMetadata` — dataclass with fields
  `iri: str`, `triple_count: int`, `last_modified: datetime | None`,
  `class_inventory: list[ClassInstanceCount]`, `graph_role: str | None`

`HolonicDataset.get_holon_detail()` is extended to include per-layer
graph metadata. Existing field names are unchanged.

### D-0.3.3-7 — Deferred: aggregate membrane health at registry level

**Status:** Open design decision, not resolved in 0.3.3.

**Context:** Per-traversal membrane health already lives in context
graphs as PROV-O activities. A holon's "current membrane health"
(the health reported by its most recent validation) is easy to
query but requires walking context. Surfacing the most-recent
health as registry metadata (e.g. `cga:currentMembraneHealth`)
would accelerate dashboards and discovery.

**Reasons to defer:**

- Mixing structural metadata (counts, types) with operational state
  (health, activity) in the same registry graph muddies the model.
- The console's polling model already re-queries context on each
  refresh, so the performance win is unclear.
- A registry-level current-health field needs eager invalidation
  semantics (when does "current" become "stale"?), which reopens
  the eager/lazy/off question from D-0.3.3-2.

**Reasons to eventually adopt:**

- Scope resolution (R9.3) would benefit from fast "find healthy
  holons within scope X" queries.
- Aggregate dashboards ("show health across 500 holons") are slow
  when each requires a context walk.
- Other operational aggregates (last traversal timestamp, recent
  error count) would want similar treatment.

**Recommendation:** Revisit in 0.3.4 alongside scope resolution.
If scope resolution needs fast health-predicate matching, introduce
registry-level health aggregates then. Otherwise, keep health in
context.

### D-0.3.3-8 — Timestamp precision and timezone

**Decision:** All metadata timestamps use `xsd:dateTime` with UTC
and microsecond precision. Python-side:
`datetime.now(timezone.utc).isoformat()`.

**Rationale:** Deterministic sort order, no timezone ambiguity,
microsecond precision covers high-rate pipeline scenarios without
sub-millisecond collisions.

### D-0.3.3-9 — MetadataRefresher as an internal class

**Decision:** Graph-metadata computation lives in a new private
class `holonic._metadata.MetadataRefresher`. `HolonicDataset`
delegates to it for all metadata work. The class is
unit-testable independently of the full dataset.

**Rationale:** Isolates the logic, keeps `client.py` from growing
another hundred lines of SPARQL-string mechanics, and makes the PR
tractable to review. The class is private (`_metadata`) because
the public API is the `HolonicDataset` methods, not the refresher
itself. If the refresher needs to be swapped (for a backend-native
implementation in 0.3.4+), it can be promoted to a protocol later.

### D-0.3.3-10 — Naming

- Existing `cga:interiorTripleCount` on `cga:Holon` retained.
- New per-graph properties on `cga:LayerGraph`:
  `cga:tripleCount`, `cga:lastModified`, `cga:refreshedAt`.
- New class for inventory records: `cga:ClassInstanceCount`.
- New predicates: `cga:inGraph`, `cga:class`, `cga:count`.
- New predicate on `cga:Holon`: `cga:holonLastModified` (rolled-up
  max of interior `lastModified` values).
- New SPARQL templates in `sparql.py`: `REFRESH_GRAPH_METADATA_TEMPLATE`,
  `COUNT_GRAPH_TRIPLES_TEMPLATE`, `COUNT_GRAPH_TYPES_TEMPLATE`,
  `ROLLUP_HOLON_METADATA_TEMPLATE`, `MIGRATE_TO_REGISTRY_TEMPLATE`.
- New config parameter: `HolonicDataset(metadata_updates: ..., registry_graph_iri: str = "urn:holarchy:registry")`.

---

## 0.3.4 — Ontological graph categories and scoped discovery

### D-0.3.4-1 — Flat class + role properties, not subclass hierarchy

**Decision:** Graph categorization uses one umbrella class
(`cga:HolonicGraph`) and a `cga:graphRole` property ranged over role
individuals:

```turtle
<urn:holon:foo/interior/radar> a cga:HolonicGraph ;
    cga:graphRole cga:InteriorRole .
```

**Alternatives considered:**

- Subclass hierarchy: `cga:InteriorGraph rdfs:subClassOf cga:HolonicGraph`,
  `?g a cga:InteriorGraph`. Shorter queries, but a graph playing two
  roles (e.g. provenance hub's interior that is both an interior and
  a provenance store) has to carry two incompatible types.

**Rationale:**

1. The ontology already uses `cga:LayerRole` individuals
   (`cga:InteriorRole`, `cga:BoundaryRole`, `cga:ProjectionRole`,
   `cga:ContextRole`) — extending them to graph-level typing reuses
   existing vocabulary.
2. Multi-role graphs are not hypothetical. `cga:AggregateHolon` in
   the existing ontology implies aggregate interiors that double as
   provenance stores or index graphs.
3. Query verbosity cost is one extra triple pattern
   (`?g a cga:HolonicGraph ; cga:graphRole cga:InteriorRole` vs
   `?g a cga:InteriorGraph`). Negligible.

**Implications:**

- Role individuals are reused for both layer-binding (`cga:LayerGraph
  cga:layerRole ?role`) and graph-categorization (`cga:HolonicGraph
  cga:graphRole ?role`). This is a deliberate merge, not a name
  collision — they describe the same concept (the role a graph plays
  in a holon's layered structure).
- Adding a new role means defining a new `cga:LayerRole` individual.
  No class-hierarchy surgery required.
- `cga:RegistryRole` is a new role individual for the registry graph
  itself, which is not a layer of any particular holon.

### D-0.3.4-2 — Write typing eagerly on registration; CLI for backfill

**Decision:** `add_interior`, `add_boundary`, `add_projection`,
`add_context` each write the typing triple to the registry
immediately. A separate migration CLI
(`scripts/holonic-migrate-registry.py`, exposed via `[project.scripts]`
as `holonic-migrate-registry`) adds typing to layer graphs registered
before 0.3.4.

**Alternatives considered:**

- Eager only. Existing deployments never get typed graphs until they
  re-register, which they may never do.
- CLI only. New registrations pay a manual step that is easily
  forgotten.

**Rationale:** Both paths are cheap. The registration-time write is
one extra triple. The CLI handles the one-time backfill for operators
who have existing holarchies. The CLI prints a diff-style summary so
operators can audit what changed before acknowledging.

**Migration semantics:**

- Idempotent: running the CLI twice is safe; it skips graphs that
  already carry the typing triple.
- Read-only by default. Pass `--apply` to actually write. Without the
  flag it prints the plan.
- Writes land in the registry graph. No content in layer graphs is
  touched.
- Exits non-zero if the registry is unreachable or malformed. Exits
  zero on no-op (everything already typed).

### D-0.3.4-3 — Narrow scope resolution for 0.3.4

**Decision:** Ship two predicate classes:

- `HasClassInInterior(class_iri)` — uses the class inventory from
  0.3.3
- `CustomSPARQL(ask_template)` — escape hatch; template binds
  `?holon` and must return an ASK result

Defer `HasPortalProducing`, `HasShapeFor`, `LabelMatches` until
usage patterns demand them. The `CustomSPARQL` escape hatch covers
these cases for 0.3.4 callers who can write their own ASK query.

**Rationale:** Two predicate classes is a tractable PR. The console
only needs `HasClassInInterior` for its initial discovery use case.
Adding more predicates is a patch-level change if evidence emerges
that `CustomSPARQL` is being abused to work around missing predicates.

### D-0.3.4-4 — Strict BFS topology, no weighting

**Decision:** `resolve(...)` performs a strict BFS from `from_holon`
through the portal graph. All 1-hop neighbors are ranked before any
2-hop neighbor. Within a single hop, order is determined by the
secondary `order` parameter (alphabetical by IRI as default tiebreak
for determinism).

**Alternatives considered:**

- Weighted walks where alignment holons score higher than data
  holons, or portals with specific properties rank above others.

**Rationale:** Weighted walks solve problems that are not yet
concrete. When a real use case surfaces, a `weight_fn` parameter can
be added additively.

**Topology direction modes** (the `order` parameter):

- `"network"` (default) — BFS through outbound portals, then
  inbound portals
- `"containment"` — BFS through `cga:memberOf` chain (parent first,
  then siblings, then descendants)
- `"reverse-network"` — BFS through inbound portals only; useful
  for "what depends on this holon" debugging queries

### D-0.3.4-5 — Scope resolution lives in `holonic.scope`

**Decision:** New `holonic.scope` module houses predicate classes,
the match dataclass, and the resolver implementation. `HolonicDataset`
delegates via `self.resolve(...)`.

**Rationale:** Parallels the `holonic._metadata` split from 0.3.3 —
keeps `client.py` from accumulating more SPARQL mechanics. Unlike
`_metadata` (private module), `scope` is public because callers need
to import predicate classes to construct them. `holonic.scope` joins
`holonic.projections` as a public module alongside the core client.

### D-0.3.4-6 — Graph-category typing uses the existing registry graph

**Decision:** Typing triples go into the registry graph established
in 0.3.3 (`urn:holarchy:registry` by default, configurable). No
separate typing graph.

**Rationale:** The registry is already the metadata catalog. Adding
graph-category triples to it keeps one queryable surface for all
graph-metadata operations. Separating them would force every
discovery query to `UNION` across graphs.

### D-0.3.4-7 — Role individual for the registry graph itself

**Decision:** The registry graph is typed on first metadata refresh:

```turtle
<urn:holarchy:registry> a cga:HolonicGraph ;
    cga:graphRole cga:RegistryRole .
```

**Rationale:** Self-description is minimal and has low blast radius.
Makes the registry discoverable by the same query pattern as any
other typed graph (`SELECT ?g WHERE { ?g a cga:HolonicGraph ;
cga:graphRole cga:RegistryRole }`). Defers the harder
"registry-as-holon" question (SPEC.md Open Question 1) — typing the
graph does not require modeling it as the interior of a RegistryHolon.

### D-0.3.4-8 — Skip health aggregates in this release

**Decision:** Per-holon health aggregates in the registry remain
deferred (see D-0.3.3-7). 0.3.4 scope resolution uses
`validate_membrane()` via `CustomSPARQL` for callers who need
health-predicate matching.

**Rationale:** Scope resolution ships usefully without health
aggregates. If the console's usage of `resolve()` reveals a common
health-filter pattern, the aggregate can be added in 0.3.5 with the
use case as shape.

### D-0.3.4-9 — Default Python implementation; no protocol extension yet

**Decision:** `resolve(...)` is implemented as a sequence of SPARQL
queries against the existing `GraphBackend` protocol surface. No new
protocol methods added in 0.3.4.

**Rationale:** Protocol split (mandatory/optional) is 0.4.0 work per
SPEC R9.5. Adding protocol methods now and removing them in 0.4.0
creates migration churn. The default Python implementation has
acceptable performance for the target scale (hundreds of holons);
backends that want native optimization get the hook in 0.4.0 along
with graph-metadata operations.

### D-0.3.4-10 — Naming

- New ontology entities: `cga:HolonicGraph` class, `cga:graphRole`
  object property, `cga:RegistryRole` individual (+ existing role
  individuals gain implicit usage in the new predicate).
- New Python module: `holonic.scope`.
- New classes: `ResolvePredicate`, `HasClassInInterior`,
  `CustomSPARQL`, `ResolveMatch`, `ResolveOrder`.
- New method: `HolonicDataset.resolve(...)`.
- New SPARQL templates: `TYPE_GRAPH_TEMPLATE`, `QUERY_GRAPH_TYPE_TEMPLATE`,
  `HAS_CLASS_IN_INTERIOR_TEMPLATE`, `WALK_PORTAL_NEIGHBORS_TEMPLATE`,
  `WALK_MEMBER_OF_TEMPLATE`, `WALK_INBOUND_PORTALS_TEMPLATE`.
- New CLI: `holonic-migrate-registry` (entry point).

---

## 0.3.5 — Projection plugin system

### D-0.3.5-1 — Pipelines as RDF, transforms as entry points

**Decision:** A projection pipeline is modeled as a
`cga:ProjectionPipelineSpec` resource in the registry graph carrying
an ordered list of `cga:ProjectionPipelineStep` entries. Python
transforms (the functions that actually manipulate graphs) are
discovered via `importlib.metadata.entry_points(group="holonic.projections")`.
Steps reference transforms by registered name, not by Python dotted
path.

**Alternatives considered:**

- Entry-point-only (no RDF modeling). Pipelines live entirely in
  Python; nothing persists across processes.
- RDF-only (no entry points). Steps reference Python transforms by
  dotted path. Every third-party transform has to expose its own
  import surface; no validation possible until run time.

**Rationale:** The hybrid matches the "dataset IS the holarchy"
principle established for portals: the pipeline is an RDF object,
addressable, portable, and recordable in provenance. The entry-point
layer gives third parties a first-class plugin path without RDF
tooling. Name lookups happen at registration time and at run time,
so a pipeline referencing a missing transform fails at registration.

### D-0.3.5-2 — Step ordering via rdf:List

**Decision:** `cga:hasStep` points to an `rdf:List` of
`cga:ProjectionPipelineStep` resources. The list provides canonical
ordering via `rdf:first` / `rdf:rest`.

**Alternatives considered:**

- Ordinal properties (`cga:stepIndex 0`, `1`, `2`). Easier to update
  with SPARQL but requires an index-maintenance burden and drifts
  when steps are inserted mid-list.

**Rationale:** RDF lists are the idiomatic way to express ordered
sequences. rdflib handles them natively. Pipelines are registered
atomically; the update-in-place case is not a target workflow for
0.3.5. If it becomes one later, switching to reified ordinals is
a non-breaking migration.

### D-0.3.5-3 — Python API shape: `ProjectionPipelineSpec` + `ProjectionPipelineStep`

**Decision:** Two new public dataclasses in `holonic.console_model`:

```python
ProjectionPipelineStep(
    name: str,                   # human-readable step label
    transform_name: str | None,  # entry-point-registered transform
    construct_query: str | None, # inline SPARQL CONSTRUCT
)

ProjectionPipelineSpec(
    iri: str,
    name: str,                   # human-readable pipeline name
    steps: list[ProjectionPipelineStep],
    description: str | None = None,
)
```

Caller-facing methods on `HolonicDataset` take these dataclasses;
internal registry writes serialize them to Turtle. A Turtle escape
hatch (`register_pipeline_ttl(ttl)`) is also provided for advanced
callers who want full control over the registry statements.

**Rationale:** Naming reflects the conceptual hierarchy:
pipeline-as-a-whole is the top-level spec, steps are subordinate.
The dataclasses keep callers out of Turtle for common cases while
preserving access for advanced ones.

### D-0.3.5-4 — All transforms (first-party + third-party) via entry points

**Decision:** The `holonic` package declares its own first-party
transforms (`strip_blank_nodes`, `localize_predicates`,
`extract_types`, `filter_by_class`, `collapse_reification`) via
`[project.entry-points."holonic.projections"]` in its own
`pyproject.toml`. Third-party packages register transforms the
same way. No hardcoded registry.

**Rationale:** Dogfooding keeps the system honest. If the entry-point
mechanism has any quirks, the library exercises them every time it
runs. No code-path divergence between first-party and third-party
transforms.

**Implication:** The library's own transforms acquire registered
names and become addressable from RDF specs. Existing Python imports
of `holonic.projections.strip_blank_nodes` continue to work — entry
points are additive, not replacing the module-level exports.

### D-0.3.5-5 — Loose provenance with host-machine metadata

**Decision:** `run_projection()` records a `prov:Activity` in the
target holon's context graph containing:

- `prov:used <pipeline_spec_iri>`
- `prov:generated <output_graph_iri>`
- `prov:startedAtTime`, `prov:endedAtTime`
- `prov:wasAssociatedWith <agent_iri>` (optional)
- `cga:transformVersion ?v` for each transform used (entry-point
  package name + version, looked up via `importlib.metadata`)
- `cga:runHost` (hostname), `cga:runPlatform` (OS + architecture),
  `cga:runPythonVersion` (Python version), `cga:runHolonicVersion`
  (holonic package version)

**Alternatives considered:** Strict recording (hash source bytecode);
no recording.

**Rationale:** Loose recording covers the common reproducibility
question ("what version of which transform ran?") without the
complexity of bytecode hashing. Host metadata adds deployment
context useful in multi-tenant or cross-environment debugging.

### D-0.3.5-6 — `run_projection` honors `metadata_updates` per D-0.3.3-5

**Decision:** `run_projection(holon_iri, spec_iri, store_as=...)`
calls `_maybe_refresh(store_as)` after writing the output graph,
same as every other library-mediated write. Extends D-0.3.3-5's
trigger list.

**Rationale:** Consistency. A projection graph is a layer graph
like any other; it should carry the same metadata as one produced
by `apply_pipeline()`.

### D-0.3.5-7 — Narrow 0.3.5 with console hook stubs

**Decision:** 0.3.5 ships:

- Spec registration and persistence
- Pipeline execution with provenance
- Entry-point transform discovery
- First-party transforms exposed via entry points
- Two predicate query helpers (`list_projection_pipelines`,
  `get_projection_pipeline`) sized for later console consumption

0.3.5 does NOT ship:

- Migration of pre-0.3.5 projection graphs to retrofit specs
- A `get_projection_activity_history(holon_iri)` method
- Console-side integration

Forward-looking note for the console:
`list_projection_pipelines(holon_iri)` returns `ProjectionPipelineSummary`
with just enough fields for a list view. The corresponding detail
method is `get_projection_pipeline(spec_iri)`. Console integration
can consume both without requiring further library changes.

### D-0.3.5-8 — New module: `holonic.plugins`

**Decision:** Entry-point discovery, transform registry, and the
`@projection_transform` decorator live in `holonic.plugins`. The
existing `holonic.projections` module continues to house the
transform functions themselves and is the package that declares
them as entry points.

**Rationale:** Keeps the plugin machinery (introspection, registry
lookups) separate from the transforms it catalogs. Parallels
the `holonic._metadata` / `holonic.scope` split: one module per
cross-cutting concern.

### D-0.3.5-9 — Transform protocol

**Decision:** A projection transform is any callable with signature
`(graph: rdflib.Graph, **kwargs) -> rdflib.Graph`. Keyword arguments
are specific to the transform; specs don't carry arguments in 0.3.5
(transforms are called with their defaults). If argument passing
becomes necessary, it can be added as a `cga:stepArguments` literal
holding a JSON blob.

**Rationale:** Matches the existing `ProjectionStep` protocol in
`holonic.projections`. No new function signature to learn.

### D-0.3.5-10 — Naming

- New ontology entities: `cga:ProjectionPipelineSpec`,
  `cga:ProjectionPipelineStep`, `cga:hasPipeline`, `cga:hasStep`,
  `cga:stepName`, `cga:transformName`, `cga:transformVersion`,
  `cga:runHost`, `cga:runPlatform`, `cga:runPythonVersion`,
  `cga:runHolonicVersion`. `cga:constructQuery` is reused from the
  existing portal vocabulary.
- New Python module: `holonic.plugins`.
- New dataclasses in `holonic.console_model`:
  `ProjectionPipelineSpec`, `ProjectionPipelineStep`,
  `ProjectionPipelineSummary`.
- New methods on `HolonicDataset`: `register_pipeline`,
  `register_pipeline_ttl`, `attach_pipeline`, `list_pipelines`,
  `get_pipeline`, `run_projection`.
- New decorator: `@projection_transform(name)`.
- New SPARQL templates: `LIST_PIPELINES_FOR_HOLON_TEMPLATE`,
  `READ_PIPELINE_DETAIL_TEMPLATE`, `PIPELINE_STEPS_TEMPLATE`.
- Entry point group: `holonic.projections`.

---

## 0.4.0 — Protocol rename and mandatory/optional split

### D-0.4.0-1 — Split shape: Protocol + ABC with defaults

**Decision:** The canonical backend interface is a Protocol
(`HolonicStore`) for mandatory methods and an ABC
(`AbstractHolonicStore`) that inherits the protocol and provides
default implementations of optional methods. Backend authors may
either (a) implement the Protocol duck-typed, getting only the
mandatory surface, or (b) inherit the ABC, getting mandatory +
optional defaults for free.

**Alternatives considered:**

- Two Protocols (mandatory and extended) with `isinstance` dispatch.
  No defaults; more boilerplate at dispatch sites.
- Single Protocol + `capabilities: set[str]` attribute. Least
  Pythonic, most flexible for backends with partial native
  support.
- Module-level dispatch functions. No protocol surface change
  beyond the rename, but no native-optimization hook either.

**Rationale:** Protocol + ABC is the textbook Python pattern for
"structural typing with recommended base class." Keeps the
existing `MetadataRefresher`/`ScopeResolver` architecture — those
helpers dispatch to native overrides via `hasattr` checks. Users
get a clean type annotation (`HolonicStore`), backend authors get
a convenient base (`AbstractHolonicStore`), and the library keeps
its generic fallback path.

### D-0.4.0-2 — Minimal optional surface for 0.4.0

**Decision:** The optional surface in 0.4.0 is a single method:
`refresh_graph_metadata(graph_iri, registry_iri)`. Additional
optional methods (scope walking, bulk load, pipeline execution)
are added additively in 0.4.x as evidence warrants.

**Rationale:** Ships the protocol split with one working example.
Proves the dispatch mechanism end-to-end. Avoids committing to
large extension surfaces before the split pattern is validated
against real backends.

### D-0.4.0-3 — Deprecation: `GraphBackend` alias through all of 0.4.x

**Decision:** `GraphBackend` remains importable as a deprecated
alias from `holonic`, `holonic.backends`, and
`holonic.backends.protocol` through every 0.4.x release.
Removal scheduled for 0.5.0.

**Suppression:** Set `HOLONIC_SILENCE_DEPRECATION=1` in the
environment. Used by CI until downstream migration is complete.

**Warning policy:** One warning per Python session per import
path. The package-level `__getattr__` tracks whether it has
warned and stays silent after the first access. Keeps CI output
readable; one-shot is enough signal.

**Rationale:** Ample runway for downstream projects
(holonic-console, hnn-scaffold, third-party backends) to
migrate. Hard removal at 0.5.0 is the forcing function. Silent
forever (never removing the alias) would clutter the public API
permanently.

### D-0.4.0-4 — `registry_graph` → `registry_iri` parameter rename

**Decision:** `HolonicDataset.__init__` accepts `registry_iri` as
the canonical name. `registry_graph` remains as a deprecated
keyword-only fallback that (a) raises `ValueError` if both are
passed and (b) emits a `DeprecationWarning` if `registry_graph`
is used. The attribute `self.registry_graph` is preserved as a
silent read-only property aliased to `self.registry_iri`, so
existing code reading the attribute continues to work without
warnings.

**Rationale:** Internal helpers (`MetadataRefresher`,
`ScopeResolver`, SPARQL templates) already use `registry_iri`.
The public parameter was the odd one out. The property alias
keeps the attribute-read path silent because warning every
`ds.registry_graph` access would be unreasonably noisy for
minimal information value.

### D-0.4.0-5 — Duck-typed acceptance; `hasattr` for native dispatch

**Decision:** `HolonicDataset.__init__` accepts any object matching
the `HolonicStore` protocol, whether it inherits the ABC or not.
Library helpers (`MetadataRefresher`, etc.) dispatch to optional
native methods via `hasattr(store, method_name)` checks, not
`isinstance` checks or capability-registry lookups.

**Rationale:** Matches Python's structural-typing idiom. Backend
authors don't have to inherit the ABC if they don't want to; they
get the full feature surface either way (just potentially slower
for the Python-fallback paths).

### D-0.4.0-6 — `FusekiBackend` constructor: `dataset` keyword-only

**Decision:** `FusekiBackend` constructor is
`FusekiBackend(base_url, *, dataset, ...)`. The previous
`FusekiBackend(base_url, dataset, ...)` positional form raises
`TypeError` in 0.4.0.

**Alternatives considered:** Keep both forms, accept a positional
`dataset` with a runtime deprecation warning.

**Rationale:** 0.4.0 is our breaking window. The fix is
mechanical — every call site changes `FusekiBackend(url, "ds")`
to `FusekiBackend(url, dataset="ds")`. Small user base per our
D-0.4.0-3 rationale; clean break is worth more than soft
migration.

### D-0.4.0-7 — First-party backends inherit the ABC

**Decision:** `RdflibBackend(AbstractHolonicStore)` and
`FusekiBackend(AbstractHolonicStore)`. First-party backends
dogfood the recommended pattern.

**Rationale:** If we advertise the ABC as the recommended base,
our own backends should use it. Keeps us honest about the
ergonomics.

### D-0.4.0-8 — No changes to other protocol surfaces (`list_holons` etc.)

**Decision:** The `list_holons` / `list_holons_summary` split from
0.3.1 is preserved as-is. The `_register_layer` argument order
stays `(holon_iri, graph_iri, predicate)`.

**Rationale:** These are real differences, not naming quirks.
`list_holons` does per-holon fan-out and returns rich
`HolonInfo`; `list_holons_summary` is single-query and returns
lightweight `HolonSummary`. Forcing them into one method with
a boolean flag would mix return types in a confusing way.
`_register_layer` is internal — no user benefit to rearranging
its arguments.

### D-0.4.0-9 — Migration documentation: `docs/MIGRATION.md`

**Decision:** A dedicated migration guide lives at
`docs/MIGRATION.md`. It covers:

- Import rename table (old path → new path)
- Parameter rename: `registry_graph` → `registry_iri`
- `FusekiBackend` constructor change
- Deprecation-warning suppression instructions
- Timeline: all aliases kept through 0.4.x, removed 0.5.0

**Rationale:** One place for downstream maintainers to check
when bumping their holonic dependency. No archaeology across
CHANGELOG entries required.

### D-0.4.0-10 — Naming

- New protocol: `HolonicStore` (replaces `GraphBackend`).
- New ABC: `AbstractHolonicStore`.
- New canonical module: `holonic.backends.store`. Old
  `holonic.backends.protocol` preserved as a deprecation shim.
- Canonical parameter: `registry_iri` (was `registry_graph`).
- Silence env var: `HOLONIC_SILENCE_DEPRECATION=1`.
- New optional protocol method: `refresh_graph_metadata(graph_iri,
  registry_iri)`. Implementations return a `GraphMetadata` or
  `None`.

### D-0.4.0-11 — Specl isolated to its own pixi environment

**Decision:** The specl git dependency is declared only under
the `deps-spec` feature, which is included in a dedicated `spec`
environment but not in the `dev` environment used for day-to-day
work. Spec tasks (`spec-translate`, `spec-validate`, `spec-score`,
`spec-badge`) are accessed via `pixi run -e spec ...`.

**Alternatives considered:**

- Keep specl in `dev` as today. Every `pixi install` pulls the
  git repo.
- Move specl to PyPI and include it as a regular dependency.
  Blocked on specl publishing to PyPI.
- Make specl a conditional dependency loaded only if a task
  requests it. Pixi doesn't have a clean primitive for this.

**Rationale:** Day-to-day contributors shouldn't pay the cost of a
git clone and resolution step for infrastructure they don't use.
Spec-driven development remains a supported workflow, but only
materializes its dependencies when invoked. First-time `pixi run -e
spec ...` resolves the environment; subsequent runs are fast.

**Consequence:** `CONTRIBUTING.md` documents the split. The README
and INSTRUCTIONS continue to reference `pixi run -e dev ...` as the
default. When specl ships to PyPI, this separation can be
revisited.

---

## 0.4.2 — Structural lifecycle completion

### D-0.4.2-1 — Orphan children rather than cascade-delete them

**Decision:** When `remove_holon(parent)` is called, any child
holons declared via `cga:memberOf <parent>` have their `memberOf`
triple removed but are themselves preserved as root-level holons.

**Alternatives considered:**

1. Cascade-delete children — matches filesystem `rm -rf` semantics.
2. Refuse to remove a holon with children — requires explicit
   detachment before deletion.
3. Orphan children — the chosen option.

**Rationale:** The `cga:memberOf` relationship expresses
containment, not ownership. Dissolving a containment scope does
not dissolve what was inside it. A research department being
closed does not delete its projects; they become top-level
projects or get reassigned. Cascade-delete would surprise users
and risk data loss. Refusing to remove with children shifts the
decision burden onto callers for what is usually a routine
operation (reorganization). Orphaning is the semantically honest
middle ground, and callers who actually want cascade-delete can
iterate over children first.

**Implications:** `remove_holon` is safe to call on any holon in
the holarchy without requiring caller awareness of the
containment topology. Downstream consumers that need
cascade-delete build it on top by listing children first.

### D-0.4.2-2 — Preserve provenance activities on `remove_holon`

**Decision:** `remove_holon` deletes the holon's four layer
graphs (interior, boundary, projection, context) and registry
entries, but does NOT search out and delete `prov:Activity`
records in OTHER holons' context graphs that happen to reference
the removed holon.

**Alternatives considered:**

1. Scrub all references to the removed holon from every context
   graph in the holarchy.
2. Leave provenance untouched — the chosen option.

**Rationale:** Provenance is immutable history. An activity
recording "holon X sent a projection to holon Y on date Z" is
true regardless of whether holon X still exists at query time.
Scrubbing provenance would degrade the audit trail and violate
PROV-O semantics. Consumers that want to filter out activities
referencing deleted holons can do so at query time with a
`FILTER EXISTS { ?holon a cga:Holon }` clause.

**Implications:** The context graphs of surviving holons may
carry references to IRIs that no longer resolve to `cga:Holon`
instances in the registry. This is correct behavior. The
`PortalTargetExistsShape` and `PortalSourceExistsShape` in
`cga-shapes.ttl` apply only to active portal definitions in the
registry, not to historical activity records in context graphs.

### D-0.4.2-3 — SELECT COUNT over ASK for existence checks

**Decision:** `remove_holon`'s existence check uses
`SELECT (COUNT(*) AS ?n) WHERE { ... }` rather than
`ASK { ... }`.

**Alternatives considered:**

1. Use `ASK` via `backend.query()` — idiomatic SPARQL for
   existence questions.
2. Use `backend.ask()` directly — bypasses the generic `query()`
   path.
3. Use `SELECT COUNT` — the chosen option.

**Rationale:** The `HolonicStore.query()` method is specified to
return a list of dict-shaped rows. ASK queries produce a single
boolean which the rdflib backend implements via a `result.vars`
iteration path that returns None, causing a `TypeError` when the
caller tries to iterate. `backend.ask()` exists as a dedicated
method, but its contract is less uniform across backend
implementations than `query()` is. SELECT COUNT returns a normal
row with an integer binding, works identically against every
backend that implements `HolonicStore`, and gives the same
answer.

**Implications:** Downstream backend implementers don't need to
specialize ASK handling to be compatible with `remove_holon`.
The pattern generalizes — any future existence-check use case in
the library can adopt the same COUNT-based idiom.

### D-0.4.2-4 — Warning severity for IconPortal / SealedPortal query shapes

**Decision:** `cga:IconPortalShape` and `cga:SealedPortalShape`
report `sh:Warning` severity (not `sh:Violation`) when a portal
of those subtypes carries a `cga:constructQuery`.

**Alternatives considered:**

1. Violation severity — matches the strictness of
   `cga:TransformPortalShape` (which uses Violation for a missing
   query).
2. No shape — rely on the `rdfs:domain cga:TransformPortal` on
   `cga:constructQuery` plus caller discipline.
3. Warning severity — the chosen option.

**Rationale:** Consider a TransformPortal temporarily reclassified
to SealedPortal for maintenance. The operator's intent is to
unblock traversal later, at which point the portal reverts to
TransformPortal. Deleting the `constructQuery` just because the
type changed would lose information the operator wants to keep.
Violation severity would force callers to choose between keeping
the query (SHACL validation fails) or losing it (losing intent).
Warning preserves the query on disk while making the misuse
visible — operators who validate their registry will see the
warning and either remove the query permanently or unblock the
portal. No shape at all leaves incoherence undetectable. Warning
is the honest middle.

**Implications:** Callers who enforce "conforms=True" strictly in
CI will see warnings from validly-intended SealedPortal
temporarily-stored queries. They can either relax the threshold
to "no Violations" or clear the query when sealing and re-add it
when unsealing. The SPEC R3.2 description documents the
expectation; callers who choose stricter enforcement can subclass
the shape and bump severity.

### D-0.4.2-5 — `add_portal()` extensibility via three new kwargs

**Decision:** `add_portal()` gains three new parameters: make
`construct_query` optional, add `portal_type`, add `extra_ttl`.
Existing positional calls continue to work.

**Alternatives considered:**

1. Add a separate `add_icon_portal()` / `add_sealed_portal()`
   method per subtype. Symmetric but creates combinatorial growth
   when downstream extensions add more subtypes.
2. Replace `add_portal()` with a builder pattern (`PortalBuilder`
   with chainable setters). More flexible but breaks the existing
   call sites and adds conceptual overhead for the common case.
3. Extend `add_portal()` with optional kwargs — the chosen option.

**Rationale:** Option 3 keeps the common case (TransformPortal
with CONSTRUCT) a one-line call identical to 0.4.0. Subtype
support appears as additional keyword arguments with sensible
defaults, so the learning curve is proportional to the
complexity of what you're building. Downstream subclasses that
carry domain-specific transformation predicates use `extra_ttl`
to supply them in a single call; they don't need a second
`backend.parse_into()` and they automatically get graph typing
(0.3.4) and metadata refresh (0.3.3) for free.

**Implications:** The signature grows from 4 positional+2 keyword
parameters to 4 positional+4 keyword parameters. Complexity in
callers is bounded because subtype-specific defaults mean most
callers still write a 3- or 4-argument call. Downstream
extensions declare their own portal subclass in their own
namespace and call `add_portal(portal_type="ext:MyPortal",
extra_ttl="...")`; the library doesn't need to know about them.

### D-0.4.2-6 — Relax portal discovery queries to match any subtype

**Decision:** `FIND_PORTALS_FROM`, `FIND_PORTALS_TO`, and
`FIND_PORTAL_DIRECT` drop their `a cga:TransformPortal` filter
and match any RDF node carrying `cga:sourceHolon` +
`cga:targetHolon`. They also gain `SELECT DISTINCT` to deduplicate
across the boundary and registry graphs.

**Alternatives considered:**

1. Keep the `cga:TransformPortal` filter, add separate discovery
   methods per subtype (`find_sealed_portals_from`, etc.).
2. Relax the filter entirely — the chosen option.
3. Make the filter configurable via a method parameter
   (`find_portals_from(source, portal_type=...)`).

**Rationale:** The `cga:sourceHolon` + `cga:targetHolon`
predicate pair uniquely identifies a portal regardless of
specific subtype — that pair IS the definitive portal structural
signature in the CGA ontology. Filtering on a specific subclass
omits valid portals that the caller should see. The only reason
the pre-0.4.2 queries had the filter was that `cga:SealedPortal`
and `cga:IconPortal` were not in common use. With 0.4.2's
extensibility work making non-TransformPortal subtypes creatable
through the public API, the filter became actively wrong. Option
3 (parameterized filter) is attractive but was deferred: no
current consumer has expressed a need to filter by subtype, and
the `PortalInfo.iri` is sufficient for consumer-side filtering
when needed.

**Implications:** This is a behavior change documented in
`CHANGELOG.md` (0.4.2 "Changed" section) and `MIGRATION.md`
(0.4.1 → 0.4.2 section). Consumers relying on the old filter's
implicit subtype-exclusion behavior must add their own filter.
Consumers that want all portal subtypes visible — the common
case — get the correct behavior without changes.

---

## How to add a decision to this document

Decisions are append-only within a release section. Each decision
has:

- **ID** — `D-<version>-<index>` for cross-reference.
- **Decision** — one paragraph or a bulleted list. The *what*.
- **Alternatives considered** — two or more options that were
  rejected, each in one line or short paragraph.
- **Rationale** — why the chosen option won against the alternatives.
- **Implications** / **Open for the future** where useful.

When a decision is overturned in a later release, the original entry
stays in place (historical record) and a new entry in the later
release section references it (`Supersedes D-0.3.3-X`).
