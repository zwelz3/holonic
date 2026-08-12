# Migration Guide

One place to find every breaking or deprecated change the library
introduces. Sections are newest-first.

---

## 0.7.x → 0.8.0

Security- and correctness-hardening release. The breaking changes below
all close audit-confirmed defects; each has a narrow, explicit escape
hatch where legacy behaviour is still needed.

### Portals no longer widen to the whole dataset (S5)

`traverse_portal()` and `traverse()` previously ran a portal's CONSTRUCT
against **every** graph in the dataset when the source holon had no
projections. A broad `WHERE` clause could therefore pull in unrelated
holons' interiors — a cross-holon PII leak.

Now the CONSTRUCT is scoped to the source holon:

1. explicit `cga:sourceLayer` on the portal wins
   (`cga:DatasetRole` → whole dataset, `cga:ProjectionRole` /
   `cga:InteriorRole` → that layer of the source);
2. otherwise the source's projections (the governed view), if any;
3. otherwise the source's own interior graphs.

If the source has neither projections nor interiors, `traverse_portal()`
now raises `ValueError` instead of silently running against everything.

**To restore the old behaviour** for a specific call, pass
`unscoped_portals_allowed=True`, or declare
`<portal> cga:sourceLayer cga:DatasetRole` on the portal.

**Your portal queries do not need rewriting.** Scoping changes which graphs
a CONSTRUCT can see, not how it is evaluated. The in-scope layers are still
presented as named graphs, so the common shape

```sparql
CONSTRUCT { ... } WHERE { GRAPH ?g { ... } }
```

keeps working — `?g` simply binds to the in-scope graph IRIs instead of
every graph in the dataset. A CONSTRUCT with no `GRAPH` clause sees the
union of the in-scope graphs, as before.

### Sealed-portal enforcement is fail-closed (S6)

The seal check no longer uses a nondeterministic `SELECT ?type ... LIMIT 1`
plus a substring test. It is now an exact `ASK { GRAPH ?g { <portal> a
cga:SealedPortal } }`. A portal typed as both `cga:SealedPortal` and some
other portal type is now reliably blocked. If you relied on a dual-typed
portal being traversable, remove the `cga:SealedPortal` type.

### Type terms are validated (S2)

`add_holon(holon_type=...)` and `add_portal(portal_type=...)` now raise
`ValueError` unless the value is a prefixed name (`prefix:Local`) or a
valid full IRI. Values that previously slipped through the loose
`":" in holon_type` check (and could inject Turtle) are rejected.

### `collect_audit_trail(since=...)` is validated as an `xsd:dateTime`

`collect_audit_trail` splices its timestamp filter into the query as *text*
rather than as a binding, so `since` is now checked before it reaches the
engine and emitted through rdflib's `n3()`. A value that is not a well-formed
`xsd:dateTime` raises `ValueError`:

```
since must be an ISO-8601 xsd:dateTime (e.g. '2026-01-31T12:00:00Z'), got '2026-01-31'
```

Previously such a value was interpolated raw. That had two consequences, and
the second is the one that affects working code:

1. A value carrying a quote could close the literal and append arbitrary
   patterns to the query — the read-path twin of S1.
2. A merely *malformed* value produced an ill-typed SPARQL comparison, which
   matched nothing and returned an **empty trail**. Callers that passed
   something unparseable got silence, not an error.

So the migration risk is not code that passes good timestamps — it is code
that passed bad ones and treated the empty result as "no activity since then".
Those call sites now raise. The two most likely forms:

| previously | now | fix |
|---|---|---|
| `since="2026-01-31"` (date only) | `ValueError` | `since="2026-01-31T00:00:00Z"` |
| `since=""` (unset config/env value) | `ValueError` | pass `None`, or omit the argument |

Note `since=""` specifically: the check is `since is not None`, not a
truthiness test, so an empty string is validated rather than skipped. If you
forward an optional value straight through, normalize it first:

```python
ds.collect_audit_trail(since=raw_since or None)
```

What is accepted (verified against the implementation): a date and time
separated by `T`, with optional fractional seconds and an optional timezone
(`Z` or `±HH:MM`). A timezone is **not** required, so both of these work:

```python
from datetime import UTC, datetime

ds.collect_audit_trail(since=datetime.now(UTC).isoformat())  # aware
ds.collect_audit_trail(since=datetime.now().isoformat())     # naive
```

Passing `datetime.isoformat()` is the recommended form for any `datetime` you
already hold. Bare dates, epoch seconds, and locale-formatted strings are not
accepted.

### Backend query bindings take rdflib terms (A1/A2)

The `**bindings` keyword on `backend.query()` / `construct()` / `ask()` now
binds by explicit rdflib term type instead of guessing from the string:

- a value that is already an rdflib `Node` (`URIRef` / `Literal` / `BNode`)
  binds verbatim, and
- any other Python value binds as a typed `Literal`.

So an IRI must be passed as `rdflib.URIRef` — of **any** scheme:

```python
from rdflib import URIRef

# 0.7.x: only urn: strings became IRIs; http:// silently bound as a literal
backend.query(q, holon="urn:holon:1")          # was OK by accident
backend.query(q, holon="http://example.org/1") # silently matched nothing

# 0.8.0: explicit and scheme-agnostic
backend.query(q, holon=URIRef("urn:holon:1"))
backend.query(q, holon=URIRef("http://example.org/1"))
```

`FusekiBackend` previously ignored `**bindings` entirely (turning a
parameterized lookup into an unfiltered scan); it now honors them via
injection-safe `n3()` substitution, matching `RdflibBackend`.

### FusekiBackend holds a pooled session; prefer `close()` / `with` (C1/P5)

`FusekiBackend` now dispatches every operation onto a long-lived
worker-thread event loop and reuses one `FusekiClient` / `aiohttp`
session for its lifetime. Two consequences:

- **It now works inside a running event loop** (Jupyter, FastAPI/aiohttp
  handlers). Previously every call raised `RuntimeError: Cannot run the
  event loop while another loop is running`. No code change is required to
  benefit.
- **It owns a background thread and an open socket pool** until released.
  Close it deterministically when done:

  ```python
  with FusekiBackend("http://localhost:3030", dataset="ds") as be:
      ...  # be.query(...), be.update(...)
  # session + worker loop torn down on exit

  # or, without a context manager:
  be = FusekiBackend("http://localhost:3030", dataset="ds")
  try:
      ...
  finally:
      be.close()
  ```

  A `weakref.finalize` handler closes the session best-effort at GC, and
  the thread is a daemon (so it never blocks interpreter exit), but calling
  `close()` avoids "Unclosed client session" warnings and frees sockets
  promptly. Calling any method after `close()` raises `RuntimeError`.

### Fail-closed traversal rollback is delta-based (C2)

`traverse(..., fail_on_breach=True)` now rolls a breach back by deleting
exactly the triples it injected, rather than replacing the whole target
interior from a pre-injection snapshot. Concurrent writes to the same
interior therefore survive a rollback. **Caveat:** `DELETE DATA` cannot
name blank nodes, so a projection that injects blank-node-bearing triples
still requires exclusive access to the target interior for the duration of
a `fail_on_breach=True` call. If you traverse concurrently into a shared
target with blank-node projections, serialize those calls yourself.

### `holarchy_summary()` health comes from persisted records (P4)

For dashboards, `holarchy_summary()` no longer re-validates every membrane on
each call. The `health_distribution` is now built from each holon's
most-recent persisted `ValidationRecord` in a single aggregate query. Two
consequences:

- A holon that has **never** been recorded via `record_validation()` (directly
  or through a `traverse()`/`validate_membrane()` flow that persists a record)
  does not appear in any health bucket. On a holarchy with no validation
  history the distribution is all-zero — where 0.7.x would have re-derived it
  live.
- To restore the old semantics (re-run pyshacl for every holon on every call),
  pass `live_health=True`:

  ```python
  # 0.8.0: recompute health live, as 0.7.x always did
  summary = ds.holarchy_summary(live_health=True)
  ```

The counts, root count, staleness count, and recent activities are unchanged.

### All library exceptions now derive from `HolonicError` (A1)

A new base class, `holonic.HolonicError`, sits under every exception the
library raises. You can now catch the whole family at once:

```python
from holonic import HolonicError

try:
    ds.traverse(source, target, fail_on_breach=True)
except HolonicError as exc:  # membrane breach, sealed portal, backend error...
    log.warning("holonic operation failed: %s", exc)
```

This is **additive**. Each exception keeps the builtin base it subclassed
before 0.8.0, so existing handlers continue to work unchanged:

| Exception | Pre-0.8.0 base | 0.8.0 bases |
| --- | --- | --- |
| `MembraneBreachError` | `Exception` | `HolonicError` |
| `SealedPortalError` | `ValueError` | `HolonicError, ValueError` |
| `FusekiError` | `RuntimeError` | `HolonicError, RuntimeError` |
| `TransformNotFoundError` | `KeyError` | `HolonicError, KeyError` |

No code change is required unless you want to adopt the broader
`except HolonicError` catch. The only observable break is for code that
asserted an exact base (e.g. `Type.__bases__ == (ValueError,)`) or that
registered `MembraneBreachError` as a *non*-library error -- it is now a
`HolonicError`.

### Projection pipeline steps run against the source graph (A3)

`ProjectionStep.apply`, `ProjectionPipeline.apply`, `apply_to_graph`, and
`apply_to_lpg` no longer take a `backend` argument. A CONSTRUCT step now
always runs against the graph it is handed -- the previous step's output --
rather than, when a backend was passed, against the entire backend dataset.

That old behaviour was a bug: `apply_pipeline()` would fold triples from
*other* holons into a single holon's projection, and multi-step pipelines
did not actually chain (each CONSTRUCT re-read the whole dataset).

```python
# 0.7.x -- backend passed through; CONSTRUCT steps hit the whole dataset
result = pipeline.apply(source_graph, backend=ds.backend)

# 0.8.0 -- materialize the source, then apply; steps stay scoped to it
result = pipeline.apply(source_graph)
```

`HolonicDataset.apply_pipeline(holon_iri, pipeline)` is unchanged and now
correctly scopes to the named holon's merged interiors -- prefer it over
calling `pipeline.apply` with a hand-built graph.

New: `ProjectionPipeline.to_spec(iri, description=None)` converts a
code-built pipeline into a declarative `ProjectionPipelineSpec` you can
`register_pipeline()` and later `run_projection()`. Transform steps must be
registered (via `@projection_transform` or the `holonic.projections`
entry-point group); an unregistered inline callable raises `ValueError`.

### `HolonicDataset` pipeline internals moved to a delegate (AR1/CQ1)

The projection-pipeline registry and execution logic now live on a
`holonic._pipelines.PipelineManager` reached via `ds._pipelines`, part of the
0.8.0 decomposition of the `HolonicDataset` god class. The public methods
(`register_pipeline`, `register_pipeline_ttl`, `attach_pipeline`,
`list_pipelines`, `get_pipeline`, `run_projection`) are unchanged and require
no migration.

Only affected: code reaching into **private** helpers that were previously
attributes of `HolonicDataset` -- `_pipeline_to_ttl`, `_step_from_node`,
`_read_pipeline_steps_ordered`, and `_record_projection_activity`. These are
now methods of `PipelineManager`; call them via `ds._pipelines.<name>(...)`.

### `HolonicDataset` console reads moved to a delegate (AR1/CQ1)

The console-oriented read methods (`list_holons_summary`, `get_holon_detail`,
`holon_interior_classes`, `holon_neighborhood`, `list_portals`, `get_portal`)
now carry their logic on a `holonic._console.ConsoleReads` delegate reached via
`ds._console`. The public methods are unchanged thin wrappers and require no
migration; only code that reached into the (private) implementation is
affected. This lifts the presentation-shaped reads out of the core dataset
surface (the audit's "core -> console layering" concern).

### `HolonicDataset` membrane validation moved to a delegate (AR1/CQ1)

`validate_membrane` and `validate_all` now carry their logic on a
`holonic._membrane.MembraneValidator` reached via `ds._membrane`. Both public
methods are unchanged thin wrappers and require no migration.

The `_no_shapes_report` helper became the module-level function
`holonic._membrane.no_shapes_report`; `HolonicDataset._no_shapes_report`
remains as a delegating `@staticmethod`, so existing callers still work.

### `HolonicDataset` provenance moved to a delegate (AR1/CQ1)

The provenance cluster now lives on a `holonic._provenance.ProvenanceLog`
reached via `ds._provenance`: `record_traversal`, `record_validation`,
`collect_audit_trail`, `portal_traversal_history`, `get_activity`,
`last_traversal`, `derivation_chain`, and `rollback_traversal`. All eight
public methods are unchanged thin wrappers and require no migration.

Only affected: code reaching into the private `_build_surface_report`, now
`ds._provenance._build_surface_report(...)`.

### `HolonicDataset` portal registry moved to a delegate (AR1/CQ1)

Portal declaration, mutation, and discovery now live on a
`holonic._portals.PortalRegistry` reached via `ds._portals`: `add_portal`,
`remove_portal`, `update_portal`, `iter_portals_from`, `find_portals_from`,
`iter_portals_to`, `find_portals_to`, `find_portal`, and `find_path`. All are
unchanged thin wrappers and require no migration.

Note the generator methods (`iter_portals_from`, `iter_portals_to`) now return
the delegate's generator rather than being generator functions themselves.
Iteration, laziness, and results are identical; only
`inspect.isgeneratorfunction(ds.iter_portals_from)` changes, from `True` to
`False`.

### `HolonicDataset` traversal moved to a delegate (AR1/CQ1)

Portal crossing now lives on a `holonic._traversal.TraversalEngine` reached via
`ds._traversal`: the public `traverse_portal`, `traverse`, `traverse_path`, and
`dry_run` remain as unchanged thin wrappers and require no migration.

This cluster moved with **no facade wrappers for its privates**, because each
was called only from within the cluster itself. Code reaching into any of
`_scoped_dataset`, `_resolve_target_interior`, `_projection_hash`,
`_inject_projection`, `_rollback_injection`, `_stored_projection_hash`,
`_store_projection_hash`, or `_record_traversal_outcome` must now go through
`ds._traversal.<name>(...)`. The in-tree test that pinned `_scoped_dataset`
(the S5 scoping property) was updated accordingly.

`_safe_layer_graph` deliberately stayed on `HolonicDataset`: holon writes,
validation, and projections all use it, so it is shared infrastructure rather
than traversal-owned.

---

## 0.6.0 → 0.7.0

No breaking changes. All additions are backward-compatible.

### collect_audit_trail() signature change

The method now accepts optional keyword arguments (`limit`,
`offset`, `since`, `kind`). Calling with no arguments returns the
full trail as before. If you were passing positional arguments
(not possible in 0.6.0), this is a no-op.

### MembraneResult has a new field

`shape_violations: list[ShapeViolation]` is added with a default
empty list. Existing code that unpacks or inspects `MembraneResult`
is unaffected; the new field is additive.

### AggregateHolonShape SPARQL constraint removed

The SPARQL constraint that checked whether AggregateHolon interiors
were populated by traversal provenance has been removed. It had two
bugs: pyshacl ignored `sh:severity sh:Warning` (always reported as
Violation), and it queried the registry graph for provenance that
lives in context graphs (so it could never be satisfied). If you
had code that depended on this constraint firing, it was already
broken; the removal makes the shape's behavior match its intent.

### New public API

`classify_sparql()`, `validate_iri()`, `get_activity()`,
`holarchy_summary()`, `on_traversal()`, `on_validation()`,
`ShapeViolation`, `HolarchySummary`. All are new; no existing
API surface is affected.

### Notebook execution in test pipeline

`pixi run test` now runs `test-notebooks` in addition to
`test-unit`. If you have notebooks with runtime errors that
previously went undetected, they will now fail the test suite.

---

## 0.5.0 → 0.6.0

One breaking change. All other additions are backward-compatible.

### Breaking: Portal CONSTRUCT queries default to projection scope

**Before (0.5.0):** Portal CONSTRUCT queries always ran against the
full dataset (union of all named graphs). A CONSTRUCT like
`WHERE { ?s a ex:Employee ; ?p ?o }` would match every triple about
employees, including PII in raw interiors.

**After (0.6.0):** When the source holon has registered projection
graphs (via `add_projection()`), the CONSTRUCT runs against the
projection graphs only. Projections exist to be the governed,
sanitized view; raw interiors may contain data the portal should
not see.

**If you need full-dataset access**, add `cga:sourceLayer
cga:InteriorRole` to the portal:

```python
ds.add_portal(
    "urn:portal:full-access", source, target, construct_query,
    extra_ttl=(
        '<urn:portal:full-access> '
        '<urn:holonic:ontology:sourceLayer> '
        '<urn:holonic:ontology:InteriorRole> .'
    ),
)
```

**If the source holon has no projections**, behavior is unchanged:
the CONSTRUCT runs against the full dataset.

---

## 0.4.3 → 0.5.0

Three breaking removals. All were deprecated in 0.4.0 with warnings
through the entire 0.4.x series.

| Removed | Replacement | Was deprecated since |
|---------|-------------|---------------------|
| `GraphBackend` (class alias) | `HolonicStore` | 0.4.0 |
| `HolonicDataset(registry_graph=...)` | `HolonicDataset(registry_iri=...)` | 0.4.0 |
| `ds.registry_graph` (property) | `ds.registry_iri` | 0.4.0 |

**Migration steps:**

1. Find and replace `GraphBackend` with `HolonicStore` in imports
   and type annotations.
2. Replace `registry_graph=` with `registry_iri=` in constructor
   calls.
3. Replace `ds.registry_graph` with `ds.registry_iri` in attribute
   access.
4. Remove `HOLONIC_SILENCE_DEPRECATION=1` from your environment.

### New features (no migration required)

| Feature | Description |
|---------|-------------|
| `add_holon(holon_type=...)` | Assert a functional subtype at creation time |
| `iter_holons(limit=, offset=)` | Generator-based lazy iteration with pagination |
| `iter_portals_from(iri, limit=, offset=)` | Generator-based portal iteration with pagination |
| `iter_portals_to(iri, limit=, offset=)` | Generator-based portal iteration with pagination |
| `list_holons(limit=, offset=)` | Existing method now accepts pagination kwargs |
| `find_portals_from(iri, limit=, offset=)` | Existing method now accepts pagination kwargs |
| `find_portals_to(iri, limit=, offset=)` | Existing method now accepts pagination kwargs |
| `bulk_load(holons=, portals=)` | Batch construction with one metadata refresh at the end |
| `export(format='trig')` | Serialize the entire dataset to TriG, N-Quads, etc. |
| `export_graph(iri, format='turtle')` | Serialize a single named graph |
| `to_dict()` on all dataclasses | JSON-ready serialization (enums converted to strings) |
| `py.typed` marker | Enables mypy/pyright type checking for downstream consumers |
| `repr(ds)` | Shows backend type, holon count, and registry IRI |

---

## 0.4.2 → 0.4.3

One breaking change. All other additions are backward-compatible.

### Breaking: `cga:dataClassification` is now an ObjectProperty

**Before (0.4.2 and earlier):**
```turtle
<urn:holon:x> cga:dataClassification "CUI" .
```

**After (0.4.3):**
```turtle
<urn:holon:x> cga:dataClassification cga:Internal .
```

The property changed from `owl:DatatypeProperty` (range `xsd:string`)
to `owl:ObjectProperty` (range `cga:ClassificationLevel`). The CGA
ontology ships five standard individuals: `cga:Public`, `cga:Internal`,
`cga:PII`, `cga:Confidential`, `cga:Restricted`) plus government tiers (`cga:CUI`, `cga:Secret`, `cga:TopSecret`).

**Migration steps:**

1. Find all triples using string-valued `cga:dataClassification`
   in your holarchy:
   ```sparql
   SELECT ?holon ?val WHERE {
       ?holon cga:dataClassification ?val .
       FILTER(isLiteral(?val))
   }
   ```
2. Replace each string literal with the corresponding IRI:
   ```sparql
   DELETE { GRAPH ?g { ?h cga:dataClassification "CUI" } }
   INSERT { GRAPH ?g { ?h cga:dataClassification cga:Internal } }
   WHERE  { GRAPH ?g { ?h cga:dataClassification "CUI" } }
   ```
3. If you used custom classification values not in the shipped
   enumeration, declare your own individuals:
   ```turtle
   ex:FOUO a cga:ClassificationLevel ; rdfs:label "FOUO" .
   ```

### New shapes (no migration required)

| Shape | Targets | Severity | What it checks |
|-------|---------|----------|----------------|
| `cga:AgentHolonShape` | `cga:AgentHolon` | Info | Should have interior, boundary, and context layers |
| `cga:AggregateHolonShape` | `cga:AggregateHolon` | Warning | Interior data without traversal provenance |

---

## 0.4.1 → 0.4.2

Zero required changes. All additions are backward-compatible.

### Behavioral changes in portal discovery

Two latent bugs were fixed. Both are behavioral changes rather than
API changes, so no code needs to move, but downstream consumers
should know about them.

**`find_portals_from/to/direct` no longer return duplicates.**
Pre-0.4.2 queries matched portal triples in every graph where the
portal appeared, so each portal came back twice.

**`find_portals_from/to/direct` now return all portal subtypes,
not just `cga:TransformPortal`.** Pre-0.4.2 queries hardcoded a
type filter that silently omitted non-TransformPortal subtypes.

---

## 0.3.x → 0.4.0

0.4.0 was the first release labeled as breaking. The changes are
small in code volume, large in naming.

### Summary

| Change | Scope |
|--------|-------|
| `GraphBackend` → `HolonicStore` | Imports, type annotations |
| `registry_graph=` → `registry_iri=` | `HolonicDataset` constructor |
| `FusekiBackend(url, ds)` → `FusekiBackend(url, dataset=ds)` | Every `FusekiBackend` construction |

The `GraphBackend` and `registry_graph` aliases were kept through
0.4.x with deprecation warnings, then removed in 0.5.0 (see above).
The `FusekiBackend` positional form was removed immediately in 0.4.0
with no compatibility shim.

---

### Getting help

- Questions on the library's design decisions: `docs/DECISIONS.md`
- Specification: `docs/SPEC.md`
- Bug reports and migration issues: file on the holonic GitHub
  repository.
