# Change Log

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-04-16

**Breaking release.** The `GraphBackend` protocol is renamed
`HolonicStore`; the old name remains as a deprecated alias
through all of 0.4.x. `FusekiBackend` requires `dataset` as a
keyword argument. See `docs/MIGRATION.md` for a full checklist.

### Added

- **`HolonicStore` protocol** (`holonic.backends.store`) —
  replaces `GraphBackend` as the canonical backend interface.
  Identical mandatory surface.
- **`AbstractHolonicStore` ABC** — recommended base class for new
  backends. Marks mandatory methods as `@abstractmethod`;
  provides a placeholder for optional-method defaults that will
  grow over 0.4.x.
- **Optional native dispatch hook**: `refresh_graph_metadata(
  graph_iri, registry_iri)`. Backends that implement this method
  are called directly by `MetadataRefresher.refresh_graph`; backends
  without it get the generic Python fallback. Dispatch is
  duck-typed via `hasattr` — no registration required.
- **`registry_iri` parameter** on `HolonicDataset`. Replaces
  `registry_graph`; the old name remains as a deprecated
  keyword-only alias.
- **`docs/MIGRATION.md`** — per-release migration guide. 0.3.x →
  0.4.0 is the first entry.
- 13 new tests in `test_deprecation_and_dispatch.py` covering
  alias warnings, suppression via environment variable,
  parameter-rename compatibility, `FusekiBackend` constructor
  enforcement, and native-dispatch hook behavior.

### Changed (breaking)

- **`FusekiBackend` constructor**: `dataset` is now keyword-only.
  `FusekiBackend("http://...", "ds")` raises `TypeError`. Use
  `FusekiBackend("http://...", dataset="ds")`.
- **First-party backends inherit `AbstractHolonicStore`**.
  `RdflibBackend` and `FusekiBackend` now extend the ABC. Client
  code that tests `isinstance(backend, HolonicStore)` still
  works; code that tests `isinstance(backend, GraphBackend)` via
  the deprecated alias also still works.

### Deprecated

- **`GraphBackend`** importable from `holonic`, `holonic.backends`,
  and `holonic.backends.protocol`. Emits `DeprecationWarning` on
  first use per module per Python session. Scheduled for removal
  in 0.5.0.
- **`registry_graph` kwarg** on `HolonicDataset`. Emits
  `DeprecationWarning` when used. Scheduled for removal in
  0.5.0. Reading `ds.registry_graph` as an attribute is silent
  and remains supported through 0.4.x.

### Deprecation suppression

Set `HOLONIC_SILENCE_DEPRECATION=1` in the environment to
suppress all 0.4.0 deprecation warnings. Intended for CI usage
until downstream migration is complete.

### Internal

- New file: `src/holonic/backends/store.py`.
- `src/holonic/backends/protocol.py` converted to deprecation
  shim using `__getattr__`.
- `src/holonic/backends/__init__.py` rewritten to export new
  canonical names with a `__getattr__`-based `GraphBackend`
  alias.
- Package-level `src/holonic/__init__.py` gains a `__getattr__`
  shim for the same purpose.
- `src/holonic/client.py`: internal attribute renamed
  `self.registry_graph` → `self.registry_iri`. All 14
  internal call sites updated.
- `src/holonic/_metadata.py`: `refresh_graph` now discovers and
  dispatches to native `refresh_graph_metadata` when present.
- First-party backends inherit `AbstractHolonicStore`.
- New docs: `docs/MIGRATION.md`, `docs/DECISIONS.md` § 0.4.0.
- **Specl moved out of the default `dev` pixi environment.**
  A new dedicated `spec` environment pulls specl from git only
  when the spec pipeline is invoked (`pixi run -e spec ...`). Keeps
  day-to-day work from depending on a git pull of specl. See
  `CONTRIBUTING.md` § "Specl (optional, for spec work)".
- **SPEC.md fully annotated for 100% maturity.** Every requirement
  carries `priority`, `constrains`, `acceptance`, and `verifiedBy`
  sub-bullets. User stories carry `asA`, `soThat`, and `acceptance`.
  Open questions reformatted as `OQ1`–`OQ7` with `owner`,
  `recommendation`, and `status` sub-bullets. Requires specl 0.2.0+
  for the Phase 1 sub-bullet parser. Score: 60/60 requirements
  clean, 0 violations, 0 warnings. Badge rendered at
  `build/spec-badge.svg` and embedded in the README.

### Limits (known, documented)

- The optional protocol surface is currently one method
  (`refresh_graph_metadata`). Scope walking, bulk load, and
  pipeline execution native hooks are planned additively for
  0.4.x releases as evidence of native-backend benefit emerges.
- The deprecation-warning system uses module-level boolean
  flags. Multi-process deployments may emit the warning once per
  process rather than once per session cluster-wide. Acceptable
  for dev ergonomics; not a concern for production.

## [0.3.5] - 2026-04-16

### Added

- **Projection plugin system.** Projection pipelines are
  RDF-modeled specs in the registry; Python transforms are
  discovered via `importlib.metadata` entry points
  (`holonic.projections` group). Pipelines reference transforms
  by registered name. See `docs/DECISIONS.md` § 0.3.5.
- **`holonic.plugins` module** with:
  - `@projection_transform(name)` decorator for first-party
    transform registration.
  - `get_registered_transforms()` — merges first-party and
    entry-point transforms; first-party wins on name collision.
  - `resolve_transform(name)` — lookup by registered name.
  - `TransformNotFoundError` — raised at registration time when
    a pipeline references an unknown transform.
  - `transform_version(name)` — returns `"<pkg-name>==<version>"`
    for provenance recording.
  - `host_metadata()` — returns dict of hostname, platform,
    Python version, holonic version.
- **First-party transforms registered via entry points**:
  `strip_blank_nodes`, `localize_predicates`,
  `collapse_reification`. Declared in `pyproject.toml` under
  `[project.entry-points."holonic.projections"]`. Third-party
  packages register the same way.
- **CGA ontology section 9 (Projection Pipeline Vocabulary)** —
  adds `cga:ProjectionPipelineSpec` class,
  `cga:ProjectionPipelineStep` class, `cga:hasPipeline`
  (`Holon → Spec`), `cga:hasStep` (`Spec → rdf:List`), plus
  `cga:stepName`, `cga:transformName`, `cga:transformVersion`,
  `cga:runHost`, `cga:runPlatform`, `cga:runPythonVersion`,
  `cga:runHolonicVersion`. `cga:constructQuery` is reused from
  the portal vocabulary.
- **New `HolonicDataset` methods**:
  - `register_pipeline(spec)` — validates transform names, writes
    spec to registry, returns the spec IRI.
  - `register_pipeline_ttl(ttl)` — raw-Turtle escape hatch for
    advanced use.
  - `attach_pipeline(holon_iri, spec_iri)` — declares holon has
    access to a pipeline.
  - `list_pipelines(holon_iri)` — returns
    `ProjectionPipelineSummary` objects for attached pipelines.
  - `get_pipeline(spec_iri)` — returns full
    `ProjectionPipelineSpec` with step order preserved via
    `rdf:List` walk.
  - `run_projection(holon_iri, spec_iri, *, store_as=None,
    agent_iri=None)` — merges interior graphs, executes steps,
    optionally stores result as a projection layer, records a
    `prov:Activity` in the holon's context graph.
- **New dataclasses in `console_model`**:
  - `ProjectionPipelineSpec` — top-level pipeline with `iri`,
    `name`, `steps`, `description`.
  - `ProjectionPipelineStep` — one step with `name`,
    `transform_name`, `construct_query`.
  - `ProjectionPipelineSummary` — lightweight listing record.
- **Four new SPARQL templates**:
  `LIST_PIPELINES_FOR_HOLON_TEMPLATE`,
  `READ_PIPELINE_DETAIL_TEMPLATE`,
  `PIPELINE_STEPS_TEMPLATE`,
  `WALK_PIPELINE_LIST_TEMPLATE`.
- **Provenance recording for projection runs.** Activities carry
  `prov:used`, `prov:generated`, `prov:startedAtTime`,
  `prov:endedAtTime`, optional `prov:wasAssociatedWith`,
  `cga:transformVersion` per transform used, and four
  `cga:run*` host-metadata fields.
- **`run_projection` honors `metadata_updates`** per D-0.3.3-5.
  When `store_as` is set and mode is `eager`, the projection
  graph's metadata refreshes automatically. Same contract as
  other library-mediated writes.
- 20 new tests in `test_plugins.py` covering registration,
  validation, attachment, listing, detail readback,
  step-ordering preservation, execution with and without
  `store_as`, provenance recording, CONSTRUCT-only steps, the
  Turtle escape hatch, and multi-pipeline-per-holon scenarios.

### Design decisions

- `docs/DECISIONS.md` § 0.3.5 documents the 10 architectural
  decisions for this release: RDF-modeled pipelines + entry-point
  transforms (hybrid), `rdf:List` for step ordering, dataclass
  naming (`ProjectionPipelineSpec` / `ProjectionPipelineStep`),
  dogfooded entry-point registration for first-party transforms,
  loose provenance with host metadata, metadata-refresh
  consistency, narrow scope with console integration hooks,
  separate `holonic.plugins` module, transform signature
  conventions, naming.

### Internal

- Files touched: `__init__.py` (version, exports),
  `client.py` (pipeline methods + helpers), `console_model.py`
  (three new dataclasses), `sparql.py` (four templates),
  `projections.py` (first-party transforms registered via
  decorator), `ontology/cga.ttl` (section 9), `pyproject.toml`
  (version, entry points), `docs/DECISIONS.md`.
- New files: `plugins.py`, `test/test_plugins.py`.

### Limits (known, documented)

- Pipeline steps do not carry per-step arguments. Transforms are
  invoked with their defaults only. For parameterized transforms
  (e.g. `filter_by_class(class_iri)`), use the
  `construct_query` step form or wait for argument support in a
  later release.
- `transform_version()` returns `None` in source-only
  environments where `holonic` is not installed as a
  distribution. In normal `pip install` / `pip install -e .`
  environments it resolves the package and version correctly.
- Pipelines with `construct_query` steps execute the CONSTRUCT
  against the current in-memory intermediate graph via
  `rdflib.Graph.query().graph`. For multi-step CONSTRUCT
  pipelines, each step sees the previous step's output, not the
  original merged interior.
- Pre-0.3.5 projections registered via `project_holon(store_as=...)`
  or `apply_pipeline(store_as=...)` remain in place but have no
  associated `cga:ProjectionPipelineSpec`. A migration to
  synthesize minimal specs for historical projections is
  deferred to a later release (SPEC R9.11).
- Console integration is intentionally deferred. The
  `list_pipelines` and `get_pipeline` methods return
  console-shaped summary/detail records ready for consumption;
  the actual UI work lives in the `holonic-console` repo.

## [0.3.4] - 2026-04-16

### Added

- **Ontological graph categories.** Named graphs carry RDF types
  in the registry via a flat + role pattern: `<graph> a
  cga:HolonicGraph ; cga:graphRole cga:InteriorRole` (or
  `BoundaryRole`, `ProjectionRole`, `ContextRole`, `RegistryRole`).
  Type-based discovery (`SELECT ?g WHERE { ?g a cga:HolonicGraph ;
  cga:graphRole cga:InteriorRole }`) works without SPARQL
  entailment. Rationale: `docs/DECISIONS.md` § D-0.3.4-1.
- **CGA ontology section 8 (Graph Type Vocabulary)** — adds
  `cga:HolonicGraph` umbrella class, `cga:graphRole` property,
  `cga:RegistryRole` individual. `cga:LayerGraph rdfs:subClassOf
  cga:HolonicGraph` makes every existing LayerGraph discoverable
  via the new vocabulary.
- **Eager typing on registration.** `add_interior`, `add_boundary`,
  `add_projection`, `add_context` now write the typing triples
  alongside the layer binding. Zero API change; one extra triple
  per registration.
- **Registry self-typing.** The registry graph itself is typed as
  `cga:HolonicGraph` with `cga:graphRole cga:RegistryRole` on the
  first metadata refresh.
- **`holonic.scope` module.** Scoped discovery across the
  holarchy. Public classes: `ResolvePredicate` (protocol),
  `HasClassInInterior`, `CustomSPARQL`, `ResolveMatch`,
  `ScopeResolver`.
- **`HolonicDataset.resolve(predicate, from_holon, *, max_depth=3,
  order="network", limit=50)`** — BFS walk through the holarchy
  returning `ResolveMatch` records. Three topologies: `"network"`
  (outbound + inbound portals, default), `"reverse-network"`
  (inbound only), `"containment"` (`cga:memberOf` chain).
  `max_depth` clamps to `[0, 100]`; `limit` clamps to `[1, 10000]`.
  Strict BFS with alphabetical tiebreaking for determinism.
- **Two predicate classes.** `HasClassInInterior(class_iri)` uses
  the 0.3.3 class inventory when present, falls back to a direct
  interior query when not. `CustomSPARQL(ask_template)` is the
  escape hatch: templates use `{holon_iri}` and `{registry_iri}`
  placeholders substituted via `str.replace` so normal SPARQL
  braces do not need escaping.
- **Migration CLI: `holonic-migrate-registry`**. Backfills graph
  typing for layer graphs registered before 0.3.4. Dry-run by
  default; `--apply` writes. Idempotent. Added as a
  `[project.scripts]` entry point; also callable as `python -m
  holonic.cli.migrate_registry`.
- **Seven new SPARQL templates**: `TYPE_GRAPH_TEMPLATE`,
  `QUERY_GRAPH_TYPE_TEMPLATE`, `LIST_UNTYPED_LAYER_GRAPHS_TEMPLATE`,
  `WALK_OUTBOUND_PORTAL_NEIGHBORS_TEMPLATE`,
  `WALK_INBOUND_PORTAL_NEIGHBORS_TEMPLATE`,
  `WALK_MEMBER_OF_NEIGHBORS_TEMPLATE`,
  `ASK_HAS_CLASS_IN_INTERIOR_TEMPLATE`.
- 27 new tests: `test_typed_graphs.py` (ontology, eager typing,
  registry self-typing, migration CLI) and `test_scope.py`
  (predicate matching, BFS ordering, depth/limit clamps, three
  order modes, CustomSPARQL, standalone ScopeResolver).

### Design decisions

- `docs/DECISIONS.md` § 0.3.4 documents the 10 architectural
  decisions: flat + role (not subclass hierarchy) for graph
  categories, eager typing + migration CLI for backfill, narrow
  predicate API (two classes), strict BFS (no weighting),
  `holonic.scope` as a public module, typing in the existing
  registry graph, registry self-typing, health aggregates
  deferred, no protocol extension, naming.

### Internal

- Files touched: `__init__.py`, `client.py` (`_register_layer` +
  `__init__` + `resolve`), `_metadata.py` (`_ensure_registry_typed`),
  `sparql.py`, `ontology/cga.ttl`, `pyproject.toml`,
  `docs/SPEC.md`, `docs/DECISIONS.md`.
- New files: `scope.py`, `cli/__init__.py`,
  `cli/migrate_registry.py`, `test/test_typed_graphs.py`,
  `test/test_scope.py`.
- Version bumped in `__init__.py` and `pyproject.toml`.

### Limits (known, documented)

- `ASK_HAS_CLASS_IN_INTERIOR_TEMPLATE` has a fallback branch that
  queries the interior graph directly if the class inventory is
  missing (because `metadata_updates="off"` and no explicit
  refresh). This keeps correctness at the cost of slower ASK
  evaluations for unregistered callers.
- Additional predicate classes (`HasPortalProducing`,
  `HasShapeFor`, `LabelMatches`) are not yet shipped. Use
  `CustomSPARQL` for these cases. Upgrade path will be additive
  if evidence warrants first-class support.
- The `GraphBackend` protocol was NOT extended. Scope resolution
  is a pure Python implementation against the existing backend
  surface. Protocol split with optional mixin is held for 0.4.0.

## [0.3.3] - 2026-04-16

### Added

- **Graph-level metadata in the registry.** Per-graph triple counts,
  last-modified timestamps, and class inventories are now materialized
  as triples in the registry graph (`urn:holarchy:registry` by default,
  configurable via `HolonicDataset(registry_graph=...)`).
- **`HolonicDataset.refresh_metadata(holon_iri)`** — recompute and
  persist metadata for all layer graphs of a holon plus the per-holon
  rollup. Use after out-of-band backend writes.
- **`HolonicDataset.refresh_all_metadata()`** — same, for every holon
  in the registry. Returns holon count.
- **`HolonicDataset.get_graph_metadata(graph_iri)`** — read the
  currently-materialized `GraphMetadata` for a graph. Returns `None`
  if nothing has been written (either `metadata_updates="off"` with no
  explicit refresh, or the graph is unknown to the registry).
- **`HolonicDataset(metadata_updates=...)` parameter** — controls
  automatic refresh policy. `"eager"` (default) runs a refresh after
  every library-mediated write to a layer graph. `"off"` suppresses
  all automatic refreshes; callers use `refresh_metadata()` explicitly.
  Lazy mode is deliberately not included; see `docs/DECISIONS.md`
  § D-0.3.3-2.
- **`console_model.GraphMetadata`** — dataclass with fields `iri`,
  `triple_count`, `last_modified`, `refreshed_at`, `class_inventory`,
  `graph_role`. Re-exported from the top-level `holonic` package.
- **`HolonDetail` extended non-breakingly** — new optional fields
  `layer_metadata: dict[str, GraphMetadata]` and
  `holon_last_modified: str | None`. `get_holon_detail()` populates
  them when registry metadata is present.
- **CGA ontology section 7 (Graph-Level Metadata)** — adds
  `cga:ClassInstanceCount` class, per-graph properties
  (`cga:tripleCount`, `cga:lastModified`, `cga:refreshedAt`), inventory
  predicates (`cga:inGraph`, `cga:class`, `cga:count`), and the
  rollup `cga:holonLastModified`.
- **Eight new SPARQL templates in `holonic.sparql`**:
  `COUNT_GRAPH_TRIPLES_TEMPLATE`, `COUNT_GRAPH_TYPES_TEMPLATE`,
  `CLEAR_GRAPH_METADATA_TEMPLATE`, `CLEAR_HOLON_METADATA_TEMPLATE`,
  `READ_GRAPH_METADATA_TEMPLATE`, `READ_GRAPH_CLASS_INVENTORY_TEMPLATE`,
  `LIST_HOLON_LAYER_GRAPHS_TEMPLATE`, `LIST_HOLON_INTERIOR_GRAPHS_TEMPLATE`.
- **Internal `holonic._metadata.MetadataRefresher`** — unit-testable
  class that owns all graph-metadata computation. Uses stable inventory
  record IRIs (`<graph>/inventory/<slug>-<8-hex-hash>`) for
  idempotent clear + insert writes. Backend-agnostic; relies only on
  the `GraphBackend` protocol.
- 20 new tests in `test_metadata.py` covering: eager/off modes,
  refresh idempotence, multi-type inventory, inventory replacement on
  re-refresh, per-holon rollup across multiple interior graphs,
  custom registry graph, and reconciliation after out-of-band writes.

### Design decisions

- New `docs/DECISIONS.md` file captures the 10 architectural decisions
  made for 0.3.3 (registry-as-single-graph, two-mode update policy,
  reified class-inventory records, per-graph + per-holon metadata
  duality, write-trigger list, public API shape, deferred health
  aggregation, timestamp conventions, internal refresher pattern,
  naming). Append-only going forward.

### Internal

- Files touched: `__init__.py`, `client.py`, `console_model.py`,
  `sparql.py`, `ontology/cga.ttl`. New file: `_metadata.py`,
  `test/test_metadata.py`, `docs/DECISIONS.md`.
- Version bumped in `__init__.py` and `pyproject.toml`.

### Limits (known, documented)

- Direct `backend.put_graph()` / `backend.update()` calls bypass the
  eager refresh hook. Use `refresh_metadata()` to reconcile.
- `metadata_updates="lazy"` is not yet offered. Deferred pending
  evidence of a concrete need.
- Aggregate membrane health is not yet materialized in the registry.
  Deferred to 0.3.4 alongside scope resolution (see `DECISIONS.md`
  § D-0.3.3-7).

## [0.3.1] - 2026-04-13

### Added

- `holonic.console_model` module with operator-tool dataclasses:
  `HolonSummary`, `HolonDetail`, `ClassInstanceCount`,
  `NeighborhoodNode`, `NeighborhoodEdge`, `NeighborhoodGraph`
  (graphology-compatible via `to_graphology()`), `PortalSummary`,
  `PortalDetail`. Exported from the top-level `holonic` package.
- `HolonicDataset.list_holons_summary()` — single-query lightweight
  holon listing, no per-holon layer fan-out. The existing
  `list_holons()` is unchanged and remains the rich-`HolonInfo` path.
- `HolonicDataset.get_holon_detail(iri)` — full descriptor including
  layer graph IRIs and an interior triple count.
- `HolonicDataset.holon_interior_classes(iri)` — `(class_iri, count)`
  pairs across all interior graphs.
- `HolonicDataset.holon_neighborhood(iri, depth=1)` — portal-bounded
  BFS subgraph shaped for direct serialization to graphology JSON.
- `HolonicDataset.list_portals()` and `get_portal(iri)` — flat portal
  browsing, separate from the source/target-keyed `find_portals_*`
  family.
- `HolonicDataset.portal_traversal_history(iri, limit=50)` — recent
  PROV-O activities scoped to one portal. Limit is clamped to 10,000
  to bound runaway queries. **Note:** the current `RECORD_TRAVERSAL`
  template does not record the portal IRI as a structured triple, so
  history is filtered by `(source, target)` pair. Correct in the
  common case of one portal per ordered pair; if multiple portals
  share endpoints, results are pooled.
- `FusekiBackend(extra_headers={...})` and the underlying
  `FusekiClient(extra_headers={...})` — sets default headers merged
  into every outbound request. Per-call headers take precedence.
  Lets external orchestrators (e.g. holonic-console) pass bearer
  tokens, mTLS-handshake hints, or tenant identifiers through.
- New SPARQL templates in `holonic.sparql`: `COLLECT_HOLONS`,
  `COUNT_INTERIOR_CLASSES_TEMPLATE`, `COUNT_INTERIOR_TRIPLES_TEMPLATE`,
  `PORTAL_TRAVERSAL_HISTORY_TEMPLATE`.

### Internal

- Files touched: `client.py`, `sparql.py`, `__init__.py`,
  `backends/_fuseki_client.py`, `backends/fuseki_backend.py`,
  plus the new `console_model.py`. CRLF line endings on the touched
  source files normalized to LF; remaining files in the repo are
  untouched.

## [0.3.0] - 2026-04-07

### Added

- Holon visualization example
- Auto-docs

### Changed

- Extensions to the OWL and SHACL ontologies

### Fixed

- RDF-native holon depth computation and tree structure
