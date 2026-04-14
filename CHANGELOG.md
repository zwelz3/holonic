# Change Log

All notable changes to this project will be documented in this file.

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
