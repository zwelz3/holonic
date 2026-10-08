# API Reference

## HolonicDataset

The primary entry point. Wraps a `HolonicStore` and exposes holon,
portal, traversal, projection, and discovery operations.

```{eval-rst}
.. autoclass:: holonic.HolonicDataset
   :members:
   :undoc-members:
   :show-inheritance:
```

## Structural Lifecycle (0.4.2)

Complete CRUD surface for holons and portals. The `add_*` methods
from earlier releases are now paired with `remove_*` counterparts,
and `add_portal()` is extensible to all portal subtypes declared in
the CGA ontology plus downstream subclasses.

**Holon lifecycle.** `HolonicDataset.add_holon(iri, label, ...)`
creates a holon; `HolonicDataset.remove_holon(iri)` performs
cascading cleanup of the registry entry, all four layer graphs,
graph-typing triples, metadata records, per-holon rollup, and every
portal where the holon is source or target. Child holons that
reference the removed holon via `cga:memberOf` are orphaned but
preserved. Provenance activities are preserved because provenance
is immutable history. Idempotent — returns `False` for a
non-existent IRI.

**Portal lifecycle.** `HolonicDataset.add_portal(iri, source_iri,
target_iri, construct_query=None, *, portal_type="cga:TransformPortal",
extra_ttl=None, ...)` supports all portal subtypes. Pass
`construct_query=None` for referential or blocked subtypes; pass
`portal_type` to select the subclass; pass `extra_ttl` for
predicates carried by downstream subclasses.
`HolonicDataset.remove_portal(portal_iri)` deletes the portal's
triples from every graph containing them while preserving the
boundary graph and sibling portals.

**Portal subtype semantics.** See [`ontology.md`](./ontology.md) for
the per-subtype `cga:constructQuery` expectations enforced by SHACL
shapes: `cga:TransformPortal` requires one, `cga:IconPortal` and
`cga:SealedPortal` must not carry one.

## Ergonomics (0.5.0)

**Subtype assertion.** `add_holon(iri, label, holon_type="cga:DataHolon")`
asserts the functional subtype at creation time without raw SPARQL.

**Generators with pagination.** `iter_holons(limit=, offset=)`,
`iter_portals_from(iri, limit=, offset=)`, and
`iter_portals_to(iri, limit=, offset=)` yield results lazily.
The `list_holons()` and `find_portals_*()` methods delegate to these
generators and also accept `limit`/`offset`.

**Bulk load.** `bulk_load(holons=[...], portals=[...])` creates
multiple holons and portals in a single batch with one metadata
refresh at the end.

**Export.** `export_graph(iri, format='turtle')` serializes a single
named graph; `export(format='trig')` serializes the entire dataset.
Common formats: `turtle`, `trig`, `nquads`, `json-ld`, `xml`.

**Serialization.** All model and console-model dataclasses provide
`to_dict()` for JSON-ready serialization. Enum values are
automatically converted to their string value.

**Typing.** The library ships a `py.typed` marker file. Downstream
consumers using mypy or pyright get full type-checking support.

## Governance & Safety (0.6.0)

**Fail-closed traversal.** `traverse(fail_on_breach=True)` validates
the target membrane after injection. If COMPROMISED, exactly the
triples this call injected are removed and `MembraneBreachError` is
raised, leaving the target as it was. The projection hash is written
only after validation passes, so a rolled-back breach never suppresses a
later retry.

SHACL `sh:targetClass` reports conformant when the target class has no
instances, so a boundary shape that targets the *expected* type does not
catch a portal that injects the *wrong* one. Since 0.9.0 a fail-closed
traversal also treats injected nodes whose types no boundary shape
targets as violations (R3.7; see "Untargeted types" below), which closes
SPEC OQ11. One limitation remains: because the rollback uses
`DELETE DATA`, a projection that injects blank nodes requires exclusive
access to the target interior for the duration of the call (see
`docs/MIGRATION.md`).

**Dry-run simulation.** `dry_run(source, target)` runs the portal's
CONSTRUCT, merges with the target's existing interior in memory, and
validates against boundary shapes. Nothing is written to the dataset.

**Multi-hop traversal.** `traverse_path(source, target)` discovers
the shortest portal path and executes `traverse()` for each hop.
Supports `fail_on_breach` and provenance recording per hop.

**Sealed portals.** `SealedPortalError` is raised when traversal is
attempted on a `cga:SealedPortal`. Use `update_portal(portal_type=
"cga:SealedPortal")` to seal a portal without removing it.

**Batch validation.** `validate_all()` validates every holon's
membrane and returns `dict[str, MembraneResult]`.

**Portal update.** `update_portal(iri, construct_query=, label=,
portal_type=)` updates portal properties in-place.

**Composition.** `compose([holon_iris], layers=)` unions interior
graphs across multiple holons into one queryable `rdflib.Graph`.

**Provenance helpers.** `last_traversal(holon_iri)` returns the most
recent `TraversalRecord`. `derivation_chain(holon_iri)` walks
`prov:wasDerivedFrom` backward to list upstream holons.

**Rollback.** `rollback_traversal(activity_iri)` undoes a traversal
by re-running the portal's CONSTRUCT and removing the projected
triples from the target interior.

**Staleness tracking.** `freshness(holon_iri)` returns a `timedelta`
since the last traversal. `is_stale(holon_iri, max_age=)` returns a
boolean. `stale_holons(max_age=)` returns all stale holons.

**Source layer scoping.** Portal CONSTRUCTs default to projection
scope when projections exist (prevents PII leaking from raw
interiors). Force full-dataset access via
`cga:sourceLayer cga:InteriorRole` on the portal.

**Batch context manager.** `with ds.batch():` suppresses per-write
metadata refresh and fires one consolidated refresh on exit. This is the
recommended wrapper for bulk ingestion: in the default `eager` mode each
`add_*` write otherwise triggers a full recompute of that graph's metadata,
so wrapping a load in `batch()` collapses N refreshes into one.

**Input validation.** All `add_*` methods validate IRIs at the API
boundary via `_validate_iri()`. Labels are escaped via `_escape_ttl()`
to prevent Turtle injection.

## Consumer Integration (0.7.1)

**Paginated audit trail.** `collect_audit_trail(limit=, offset=,
since=, kind=)` pushes filtering to the SPARQL engine via
`ORDER BY DESC(?timestamp) LIMIT/OFFSET`. Calling with no
arguments returns the full trail (backward compatible).

**Activity lookup.** `get_activity(activity_iri)` returns a
`TraversalRecord` or `ValidationRecord` for a single provenance
activity. Eliminates the O(all) scan through `collect_audit_trail()`.

**SPARQL classification.** `classify_sparql(query)` returns the
query form (`'select'`, `'ask'`, `'construct'`, `'describe'`,
`'update'`). Strips comments and string literals before matching.

**IRI validation.** `validate_iri(iri)` is the public entry point
to the library's IRI validation. Raises `ValueError` for unsafe
characters.

**Dashboard summary.** `holarchy_summary(max_age=, recent_limit=,
live_health=False)` returns a `HolarchySummary` with holon count, portal
count, root count, health distribution, staleness count, and recent
activities. As of 0.8.0 it runs a handful of aggregate queries rather than
~4+N round-trips: health is read from each holon's most-recent persisted
`ValidationRecord` by default (holons never validated do not contribute to
the distribution). Pass `live_health=True` to re-validate every membrane on
the call instead — accurate but O(N). See `docs/MIGRATION.md`.

**Notification hooks.** `on_traversal(callback)` and
`on_validation(callback)` register callbacks that fire
synchronously after each `traverse()` or `validate_membrane()`.
Eliminates polling for same-process event detection.

**Structured violations.** `ShapeViolation` dataclass with
`shape_iri`, `focus_node`, `path`, `value`, `message`, `severity`.
`MembraneResult.shape_violations` carries a `list[ShapeViolation]`
populated from the pyshacl report graph. A result whose severity is not
`sh:Warning` or `sh:Info` counts as a violation, including a custom or
missing severity, so an unrecognized report cannot pass a breach (0.9.0).
`sh:Info` results are kept in `MembraneResult.infos` and never lower health.

**Untargeted types (0.9.0).** SHACL validates only the nodes its shapes
target. `MembraneResult.untargeted` lists the typed interior nodes no boundary
shape targets, as `UntargetedNode(focus_node, types, severity)`. They are
reported at Info unless the holon's boundary declares
`cga:untargetedTypeSeverity`; `traverse(..., fail_on_breach=True)` treats the
nodes it injected as violations by default. `cga:permitsType` in the boundary
exempts a class and its subclasses.

## Store Protocol (0.4.0)

```{eval-rst}
.. autoclass:: holonic.HolonicStore
   :members:

.. autoclass:: holonic.AbstractHolonicStore
   :members:
   :show-inheritance:
```

> The `GraphBackend` alias was removed in 0.5.0. Use `HolonicStore`.
> See `docs/MIGRATION.md`.

## Model Types

```{eval-rst}
.. autoclass:: holonic.HolonInfo
   :members:

.. autoclass:: holonic.PortalInfo
   :members:

.. autoclass:: holonic.MembraneResult
   :members:

.. autoclass:: holonic.MembraneHealth
   :members:

.. autoclass:: holonic.MembraneBreachError
   :members:

.. autoclass:: holonic.SurfaceReport
   :members:

.. autoclass:: holonic.AuditTrail
   :members:

.. autoclass:: holonic.TraversalRecord
   :members:

.. autoclass:: holonic.ValidationRecord
   :members:
```

## Console Model (0.3.1+)

Lightweight dataclasses tuned for JSON serialization to web clients.

```{eval-rst}
.. autoclass:: holonic.HolonSummary
   :members:

.. autoclass:: holonic.HolonDetail
   :members:

.. autoclass:: holonic.ClassInstanceCount
   :members:

.. autoclass:: holonic.NeighborhoodNode
   :members:

.. autoclass:: holonic.NeighborhoodEdge
   :members:

.. autoclass:: holonic.NeighborhoodGraph
   :members:

.. autoclass:: holonic.PortalSummary
   :members:

.. autoclass:: holonic.PortalDetail
   :members:
```

## Graph-Level Metadata (0.3.3)

```{eval-rst}
.. autoclass:: holonic.GraphMetadata
   :members:
```

See `HolonicDataset.refresh_metadata()`, `refresh_all_metadata()`,
and `get_graph_metadata()` for the read/write surface.

## Scope Resolution (0.3.4)

```{eval-rst}
.. autoclass:: holonic.ResolveMatch
   :members:

.. autoclass:: holonic.HasClassInInterior
   :members:

.. autoclass:: holonic.CustomSPARQL
   :members:

.. autoclass:: holonic.ScopeResolver
   :members:
```

`ResolvePredicate` is a `typing.Protocol`. Implementations
(`HasClassInInterior`, `CustomSPARQL`) are shown above. Custom
predicates need only a `matches(backend, holon_iri, registry_iri) -> bool`
method and an `evidence() -> str` method.

See `HolonicDataset.resolve()` for the driver.

## Projection Pipelines (0.3.5)

```{eval-rst}
.. autoclass:: holonic.ProjectionPipelineSpec
   :members:

.. autoclass:: holonic.ProjectionPipelineStep
   :members:

.. autoclass:: holonic.ProjectionPipelineSummary
   :members:
```

See `HolonicDataset.register_pipeline()`, `attach_pipeline()`,
`list_pipelines()`, `get_pipeline()`, and `run_projection()` for the
driver surface.

## Plugin System (0.3.5)

```{eval-rst}
.. autoclass:: holonic.TransformNotFoundError
   :members:

.. autofunction:: holonic.projection_transform

.. autofunction:: holonic.resolve_transform

.. autofunction:: holonic.get_registered_transforms
```

Third-party transforms register via the `holonic.projections`
entry-point group in their `pyproject.toml`:

```toml
[project.entry-points."holonic.projections"]
my_transform = "mypkg.transforms:my_transform"
```

First-party transforms register via the `@projection_transform`
decorator. Both are discovered by `get_registered_transforms()`.

## Projection Types

```{eval-rst}
.. autoclass:: holonic.ProjectedGraph
   :members:

.. autoclass:: holonic.ProjectedNode
   :members:

.. autoclass:: holonic.ProjectedEdge
   :members:

.. autoclass:: holonic.ProjectionPipeline
   :members:

.. autoclass:: holonic.ProjectionStep
   :members:
```

## Backends

See [`backends.md`](./backends.md) for the full backend surface:
`RdflibBackend` (in-memory default), `FusekiBackend` (Apache Jena
Fuseki via SPARQL over HTTP), and guidance on implementing a custom
backend.
