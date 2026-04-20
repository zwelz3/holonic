# Migration Guide

One place to find every breaking or deprecated change the library
introduces. Updated at each release that introduces any.

---

## 0.3.x → 0.4.0

0.4.0 is the first release labeled as breaking. The changes are
small in code volume, large in naming. Mechanical search-and-replace
covers almost everything.

### Summary

| Change | Required? | Scope |
|--------|-----------|-------|
| `GraphBackend` → `HolonicStore` | Recommended; alias remains through 0.4.x | Imports, type annotations |
| `registry_graph=` → `registry_iri=` | Recommended; alias remains through 0.4.x | `HolonicDataset` constructor |
| `FusekiBackend(url, ds)` → `FusekiBackend(url, dataset=ds)` | **Required** | Every `FusekiBackend` construction |
| `AbstractHolonicStore` as recommended base | Optional | New backend implementations |

### Silence deprecation warnings

While you migrate, suppress the new `DeprecationWarning`s:

```bash
export HOLONIC_SILENCE_DEPRECATION=1
```

Or in Python:

```python
import os
os.environ["HOLONIC_SILENCE_DEPRECATION"] = "1"
import holonic  # before any holonic imports
```

Warnings still appear in CI output if you don't set this. That's
intentional — you should see them once per session so you can track
migration progress. Remove the env var once you've updated.

### Step 1 — Rename protocol imports

Search for `GraphBackend`, replace with `HolonicStore`.

```diff
-from holonic import GraphBackend
+from holonic import HolonicStore

-from holonic.backends import GraphBackend
+from holonic.backends import HolonicStore

-from holonic.backends.protocol import GraphBackend
+from holonic.backends.store import HolonicStore

-def make_dataset(backend: GraphBackend) -> HolonicDataset:
+def make_dataset(backend: HolonicStore) -> HolonicDataset:
     return HolonicDataset(backend=backend)

-class MyBackend(GraphBackend):
+class MyBackend(AbstractHolonicStore):
     ...
```

The deprecated aliases still resolve to the same object (`HolonicStore`
is the Protocol that `GraphBackend` aliased), so existing
`isinstance(x, GraphBackend)` checks still pass. The alias is
scheduled for removal in 0.5.0.

### Step 2 — Rename `registry_graph` kwarg

```diff
 ds = HolonicDataset(
     backend,
-    registry_graph="urn:my:registry",
+    registry_iri="urn:my:registry",
 )
```

Attribute reads of `ds.registry_graph` continue to work silently
(they return the same value as `ds.registry_iri`). Only the
constructor kwarg warns.

### Step 3 — `FusekiBackend` keyword-only dataset

This is the one unavoidable change:

```diff
-backend = FusekiBackend("http://localhost:3030", "holarchy")
+backend = FusekiBackend("http://localhost:3030", dataset="holarchy")
```

No compat shim. If you miss a call site, you get a clear
`TypeError` from Python — not a silent behavior change.

### Step 4 — Consider adopting `AbstractHolonicStore` for new backends

For new backend implementations, inherit the ABC:

```python
from holonic.backends import AbstractHolonicStore

class MyBackend(AbstractHolonicStore):
    def graph_exists(self, graph_iri: str) -> bool: ...
    # ... other mandatory methods
    # Optional methods can be added (e.g. refresh_graph_metadata)
    # or left as Python fallbacks via the library helpers.
```

The ABC marks mandatory methods as `@abstractmethod`, so Python
will refuse to instantiate a subclass that forgets one. Backends
that prefer pure-Protocol duck-typing still work — the ABC is
recommended, not required.

### Step 5 — (Optional) Implement `refresh_graph_metadata` natively

If your backend can compute graph metadata faster than the generic
Python `MetadataRefresher` (e.g. via a native count query or
server-side stored procedure), add the optional method:

```python
class MyBackend(AbstractHolonicStore):
    # ... mandatory methods ...

    def refresh_graph_metadata(
        self,
        graph_iri: str,
        registry_iri: str,
    ) -> GraphMetadata | None:
        # Your fast path: compute counts + inventory + write to registry
        # Return GraphMetadata, or None to let the library re-read via read()
        ...
```

`MetadataRefresher.refresh_graph` discovers the method via
`hasattr` and dispatches to it automatically. If absent, the
generic Python implementation runs. No registration required.

### Timeline

- **0.4.0**: aliases land, warnings introduced, `FusekiBackend`
  positional form removed
- **0.4.1**: documentation/hygiene release; no migration required
- **0.4.2**: structural lifecycle completion (`remove_holon`,
  `remove_portal`, extensible `add_portal`); no migration
  required — all additions are backward-compatible. See the 0.4.2
  section below for two behavioral changes worth knowing about.
- **0.4.x beyond**: warnings continue unchanged
- **0.5.0**: `GraphBackend` alias removed, `registry_graph` kwarg
  removed, `ds.registry_graph` property removed

---

## 0.4.1 → 0.4.2

Zero required changes. All three additions are backward-compatible:

| Change | Required? | Notes |
|--------|-----------|-------|
| `remove_holon` / `remove_portal` | Optional (new surface) | Adopt when structural evolution (split, merge, prune) enters your use case |
| `add_portal(construct_query=None, portal_type=..., extra_ttl=...)` | Optional (new kwargs) | Existing positional `add_portal(iri, source, target, query)` calls keep working |
| `cga:IconPortal` class added to ontology | None | Previously referenced but undeclared; now available |
| `cga:IconPortalShape`, `cga:SealedPortalShape` | None | Warn (not Violate) if an Icon/Sealed portal carries a constructQuery |

### Behavioral changes in portal discovery

Two latent bugs were fixed as side effects of 0.4.2's work on
portal subtype support. Both are behavioral changes rather than
API changes, so no code needs to move, but downstream consumers
should know about them.

**`find_portals_from/to/direct` no longer return duplicates.**
Pre-0.4.2 queries matched portal triples in every graph where the
portal appeared (typically the boundary graph AND the registry
mirror), so each portal came back twice. Consumers that de-duped
on their side can now skip that step. Consumers that relied on
the count of returned rows for any reason must update their
expectations.

**`find_portals_from/to/direct` now return all portal subtypes,
not just `cga:TransformPortal`.** Pre-0.4.2 queries hardcoded a
type filter that silently omitted any portal whose type was not
`cga:TransformPortal`. This was inconsistent with the ontology,
which always declared `cga:SealedPortal` as a valid subclass. The
new queries match any node with `cga:sourceHolon` and
`cga:targetHolon`, regardless of specific subtype. If a downstream
consumer actually wanted the old filter, it can re-add a type
check at the consumer level by filtering the returned
`PortalInfo` list.

### Getting help

- Questions on the library's design decisions: `docs/DECISIONS.md`
- Specification: `docs/SPEC.md`
- Bug reports and migration issues: file on the holonic GitHub
  repository.
