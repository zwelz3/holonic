# Roadmap

The roadmap proper lives in [`SPEC.md`](./SPEC.md) as `R9.*` requirements and
`OQ1`–`OQ11` open questions. That is the machine-checked source: each item
carries a priority, an acceptance criterion, an `implementation:` status that
feeds the progress score, and — once built — a `verifiedBy` link to the test
that holds it.

This file is the human-readable view of the same thing. It exists so a reader
can see where the project has been and where it is going without parsing a
69KB specification. **When the two disagree, `SPEC.md` is right.**

Each iteration names its theme; implementation order within an iteration is
fluid.

## Next

Roughly in priority order, though items are not strictly sequenced.

- Migrate the remaining string-assembled SPARQL to parameterized queries.
  Backend `**bindings` now bind by rdflib term type, but a few read paths
  (notably `collect_audit_trail`) still assemble filters as query text.
- `find_path()` uses a Python BFS where R4.5 requires SPARQL. Currently the
  only outright compliance failure in `scripts/spec_compliance_check.py`.
- Mark the Fuseki tests skip-when-unavailable (R8.2). The second compliance
  failure.
- Aggregated membrane health in the registry (R9.13)
- Additional scope predicate classes (R9.14)
- Optional BFO/CCO and gist alignment modules (OQ10)
- Federation semantics across multiple registries (OQ7)
- Async variant of `HolonicStore` (R2.5)
- Resolve the SHACL target-class gap for `fail_on_breach` (OQ11)
- Holarchy graph with `to_graphology()` (upstream #7)
- `find_path()` adjacency caching (upstream #9)
- Decide the fate of the 13 CGA terms that are modelled but not implemented;
  see `test_ontology_utilization.py` for the current accounting.

See [`source/dom-comparison.md`](./source/dom-comparison.md) for the framing of
how the current synchronous API already maps onto DOM concepts; the open
question is whether explicit machinery is warranted.

## Shipped

- **0.8.0** — Security and correctness hardening driven by a third-party audit
  (3 critical, 37 high findings). **Breaking:** portal CONSTRUCTs scope to the
  source holon instead of widening to the whole dataset,
  `collect_audit_trail(since=)` is validated as an `xsd:dateTime`,
  `holon_type`/`portal_type` terms are validated, `ProjectionPipeline`
  execution methods drop `backend=`, and backend `**bindings` bind by rdflib
  term type. Completed the `HolonicDataset` god-class decomposition (AR1/CQ1) —
  membrane validation, provenance, portal registry, and traversal now live on
  delegates. Sealed-portal enforcement and traversal rollback are fail-closed;
  `FusekiBackend` holds a pooled session (C1/P5); all exceptions derive from
  `HolonicError` (A1). yFiles 1.x and 2.x both supported.
- **0.7.1** — Bugfix: explicit `holonic` install cell per JupyterLite notebook.
- **0.7.0** — Upstream consumer integration.
  `collect_audit_trail(limit=, offset=, since=, kind=)` with SPARQL-level
  pagination. `classify_sparql()`, `validate_iri()`, `get_activity()`,
  `holarchy_summary()`. `on_traversal()`/`on_validation()` notification hooks.
  `ShapeViolation` structured type with `MembraneResult.shape_violations`.
  AggregateHolonShape SPARQL constraint removed (queried wrong graph). Notebook
  execution wired into `pixi run test`.
- **0.6.0** — Governance enforcement and audit remediation. **Breaking:** portal
  CONSTRUCT scoping defaults to projections (R9.35). 14 new methods
  (`traverse_path`, `dry_run`, `compose`, `validate_all`, `update_portal`,
  `fail_on_breach`, `rollback_traversal`, `last_traversal`, `derivation_chain`,
  `freshness`, `is_stale`, `stale_holons`, `SealedPortalError`, `batch`).
  Third-party audit: Turtle injection fixed (C1), `get_graph` copy semantics
  (C2), IRI validation (S4), structured SHACL parsing (M1), batch context
  manager (M3). Snapshot rollback (M2), concurrency docs (M4), pydantic removed
  (O4).
- **0.5.0** — Breaking cleanup: removed the `GraphBackend` alias and the
  `registry_graph` kwarg/property (R9.18). Added the `holon_type` kwarg,
  `iter_holons`/`iter_portals_*` generators with `limit`/`offset` pagination
  (R9.11), `bulk_load()` for batch holarchy construction. `list_named_graphs()`
  confirmed mandatory (R9.17). Notebook reorganization with a sectioned landing
  page.
- **0.4.3** — Ontology enrichment: all 68 properties defined, holon subtype
  shapes (AgentHolon, AggregateHolon), ClassificationLevel enum (**breaking:**
  `dataClassification` is now an ObjectProperty), OQ10 upper-ontology alignment
  strategy.
- **0.4.2** — Structural lifecycle completion: `remove_holon`, `remove_portal`,
  extensible `add_portal` supporting all CGA portal subtypes plus downstream
  subclasses (R9.20, R9.21, R9.22).
- **0.4.1** — JupyterLite in-browser docs, dispatch-patterns notebook, DOM
  comparison framing, visualization notebook restored (R9.19).
- **0.4.0** — `HolonicStore` protocol (renamed from `GraphBackend`), ABC split,
  optional native-dispatch hook (R9.8 – R9.10).
- **0.3.x** — Typed graphs, scope resolution, graph-level metadata, projection
  plugin system (R9.1 – R9.7).

## Spec maturity

Tracked in [`spec-history.ttl`](./spec-history.ttl), one assessment per
release. See the note at the top of that file's task in `pixi.toml`
(`spec-history`) for why it is release-cadence rather than per-build.
