# Migration Guide

One place to find every breaking or deprecated change the library
introduces. Sections are newest-first.

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
