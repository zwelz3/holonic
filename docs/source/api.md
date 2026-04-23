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
