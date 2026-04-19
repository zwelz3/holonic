---
spec_id: holonic-001
title: Holonic Library — Graph-Native Holonic RDF Systems
version: 0.4.0
status: prototype
authors: [zwelz3]
---

# Intent

Provide a Python library that implements Cagel's four-graph holon model on top of RDF named graphs, enabling distributed knowledge systems to expose genuine inside/outside distinction, governed traversal, and event-level provenance without inventing new query languages or wire protocols. The library is a client-side coordination layer in front of any quad-aware graph store (rdflib, Apache Jena Fuseki, Oxigraph, GraphDB) — not a graph database itself.

# Purpose

Make it practical to build holarchies for digital engineering, defense C2, enterprise knowledge graphs, and agentic memory systems. A holon is a named IRI whose four layers (interior, boundary, projection, context) live as named graphs in the quad store; portals are RDF entities carrying SPARQL CONSTRUCT queries; membranes are SHACL shapes. All state lives in the graph. Python is a thin convenience layer over SPARQL and PROV-O.

# Requirements

## R1 Four-Graph Model

- R1.1 Each holon MUST have an IRI that threads through four named-graph layers: interior, boundary, projection, and context.
  - priority: MUST
  - constrains: HolonicDataset, cga:Holon
  - acceptance: Given a fresh HolonicDataset, when add_holon(iri, label) is called, then the holon's IRI is registered as cga:Holon and its four layer graphs resolve via cga:hasInterior, cga:hasBoundary, cga:hasProjection, and cga:hasContext.
  - verifiedBy: src/holonic/test/test_holon.py::test_add_holon_registers_four_layers

- R1.2 A holon MAY have multiple named graphs in any one layer role (e.g. `urn:holon:x/interior/radar` and `urn:holon:x/interior/fusion`); operations that read a layer MUST treat the set as a union.
  - priority: MUST
  - constrains: HolonicDataset, cga:LayerRole
  - acceptance: Given a holon with two interior graphs added with different graph_iri values, when a SPARQL union query ranges over GRAPH ?g patterns, then triples from both graphs match.
  - verifiedBy: src/holonic/test/test_holon.py::test_multi_interior_union_read

- R1.3 Layer membership MUST be declared via `cga:hasInterior`, `cga:hasBoundary`, `cga:hasProjection`, `cga:hasContext`. Layer graph IRIs MUST be discoverable by SPARQL from the holon IRI; discovery by IRI suffix convention is forbidden as a correctness mechanism.
  - priority: MUST
  - constrains: HolonicDataset, cga.ttl
  - acceptance: Given a holon with all four layers populated, when the registry is queried with SPARQL following cga:hasInterior et al., then every layer graph IRI is returned without relying on string patterns.
  - verifiedBy: src/holonic/test/test_holon.py::test_layer_discovery_via_sparql

- R1.4 The library MUST NOT flatten named graphs to a single default graph at any layer in the stack. Every triple belongs to a named graph.
  - priority: MUST
  - constrains: HolonicDataset, HolonicStore
  - acceptance: Given any library-mediated write, when inspecting the backend's default graph, then no triples produced by the library appear there.
  - verifiedBy: src/holonic/test/test_backend.py::test_writes_never_hit_default_graph

## R2 Store Protocol

- R2.1 A `HolonicStore` protocol MUST provide quad-aware named-graph CRUD (`graph_exists`, `get_graph`, `put_graph`, `post_graph`, `delete_graph`, `parse_into`, `list_named_graphs`) and SPARQL dispatch (`query`, `construct`, `ask`, `update`).
  - priority: MUST
  - constrains: HolonicStore, RdflibBackend, FusekiBackend
  - acceptance: Given an RdflibBackend instance, when isinstance checked against HolonicStore, then the check passes; every listed method exists and accepts the declared signature.
  - verifiedBy: src/holonic/test/test_backend.py::test_rdflib_backend_implements_protocol

- R2.2 An in-memory backend (`RdflibBackend`) MUST be shipped so the library is usable with no running server.
  - priority: MUST
  - constrains: RdflibBackend
  - acceptance: Given only the base `pip install holonic`, when HolonicDataset() is called without arguments, then a working instance is returned with RdflibBackend bound as the default.
  - verifiedBy: src/holonic/test/test_backend.py::TestRdflibBackend

- R2.3 An HTTP backend (`FusekiBackend`) MUST be shipped for Apache Jena Fuseki via SPARQL 1.1 and the W3C Graph Store Protocol.
  - priority: MUST
  - constrains: FusekiBackend
  - acceptance: Given a running Fuseki server, when FusekiBackend(url, dataset=ds) is instantiated and used with HolonicDataset, then CRUD and SPARQL operations round-trip through HTTP against the server.
  - verifiedBy: src/holonic/test/test_console_methods.py::TestFusekiBackend

- R2.4 `FusekiBackend` MUST accept `extra_headers` at construction so external orchestrators can pass bearer tokens, mTLS hints, or tenant identifiers through to Fuseki.
  - priority: MUST
  - constrains: FusekiBackend, _fuseki_client
  - acceptance: Given FusekiBackend(url, dataset=ds, extra_headers={"Authorization": "Bearer x"}), when any HTTP request is issued, then the header is present on the outbound request.
  - verifiedBy: src/holonic/test/test_console_methods.py::test_fuseki_client_stores_extra_headers

- R2.5 The protocol MUST remain synchronous. Async consumers wrap calls in their own thread-pool bridge; an async variant, if added, MUST be a separate protocol and not replace the sync one.
  - priority: MUST
  - constrains: HolonicStore
  - acceptance: Given the HolonicStore protocol definition, when method signatures are inspected, then none are declared with async def and no awaitables are returned.
  - verifiedBy: src/holonic/backends/store.py (structural, enforced by type system)

- R2.6 Backend method return types MUST use `rdflib.Graph` for CONSTRUCT and graph-fetch operations to preserve rdflib's serialization, iteration, and SPARQL evaluation surface.
  - priority: MUST
  - constrains: HolonicStore, RdflibBackend, FusekiBackend
  - acceptance: Given store.get_graph() or store.construct() is called, when the return value is inspected, then it is an rdflib.Graph instance supporting serialize(), iteration, and further SPARQL queries.
  - verifiedBy: src/holonic/test/test_backend.py::test_get_graph_returns_rdflib_Graph

## R3 CGA Ontology and Membrane Validation

- R3.1 The package MUST ship the Context-Graph Architecture (CGA) ontology (`cga.ttl`) and SHACL shapes (`cga-shapes.ttl`) as package data.
  - priority: MUST
  - constrains: cga.ttl, cga-shapes.ttl, package-data declaration
  - acceptance: Given `pip install holonic`, when the package is introspected, then both TTL files are present as resources under holonic.ontology and parse cleanly with rdflib.
  - verifiedBy: src/holonic/test/test_ontology.py::test_cga_ttl_packaged_and_parseable

- R3.2 The ontology MUST define `cga:Holon` and its functional subclasses (`cga:DataHolon`, `cga:AlignmentHolon`, `cga:AgentHolon`, `cga:GovernanceHolon`, `cga:AggregateHolon`, `cga:IndexHolon`), `cga:Portal` and its subclasses (`cga:TransformPortal`, `cga:IconPortal`, `cga:SealedPortal`), `cga:LayerGraph`, and `cga:LayerRole`. Portal subtype semantics MUST be enforced by SHACL shapes in `cga-shapes.ttl`: `cga:TransformPortal` requires exactly one `cga:constructQuery`; `cga:IconPortal` and `cga:SealedPortal` must not carry `cga:constructQuery` (carrying one is semantically incoherent because an IconPortal is purely referential and a SealedPortal blocks traversal).
  - priority: MUST
  - constrains: cga.ttl
  - acceptance: Given cga.ttl, when SPARQL queries every declared class, then all listed class IRIs are returned with their subclass relationships intact.
  - verifiedBy: src/holonic/test/test_ontology.py::test_ontology_declares_expected_classes

- R3.3 The ontology MUST use RDFS plus minimal OWL (class hierarchy, domain/range). The library MUST NOT depend on an OWL reasoner for correctness of any method.
  - priority: MUST
  - constrains: cga.ttl, HolonicDataset
  - acceptance: Given an rdflib-backed HolonicDataset, when the entailment extra is not installed, then every library method produces correct results without a reasoner.
  - verifiedBy: src/holonic/test/ (entire suite runs without owlrl installed)

- R3.4 `validate_membrane(holon_iri)` MUST run pyshacl against the union of the holon's interior graphs using the union of its boundary graphs and MUST return a `MembraneResult` with one of `Intact` / `Weakened` / `Compromised`.
  - priority: MUST
  - constrains: HolonicDataset.validate_membrane, MembraneResult
  - acceptance: Given a holon whose interior violates a boundary shape, when validate_membrane is called, then result.health is MembraneHealth.Compromised and result.violations lists the specific SHACL failures.
  - verifiedBy: src/holonic/test/test_membrane.py::test_validate_membrane_compromised

- R3.5 Membrane health MUST be recordable in the context graph as `cga:membraneHealth` on a `prov:Activity`.
  - priority: MUST
  - constrains: HolonicDataset.record_validation, cga.ttl
  - acceptance: Given a governed traversal with validate=True, when the activity is read from the context graph, then cga:membraneHealth is present and matches the MembraneResult.health value.
  - verifiedBy: src/holonic/test/test_audit.py::test_membrane_health_on_activity

## R4 Portal and Traversal Semantics

- R4.1 Portals MUST be first-class RDF entities stored in boundary graphs with `cga:sourceHolon`, `cga:targetHolon`, and (for `cga:TransformPortal`) `cga:constructQuery`.
  - priority: MUST
  - constrains: HolonicDataset.add_portal, cga:Portal, cga:TransformPortal
  - acceptance: Given add_portal(iri, source, target, construct_query, label), when the registry is queried, then the portal is found with cga:sourceHolon, cga:targetHolon, and cga:constructQuery as RDF triples.
  - verifiedBy: src/holonic/test/test_portal.py::test_portal_is_first_class_rdf

- R4.2 Portal discovery MUST be SPARQL-driven (`find_portals_from`, `find_portals_to`, `find_portal`, `find_path`). Python-side iteration over cached portal objects is forbidden.
  - priority: MUST
  - constrains: HolonicDataset discovery methods, sparql.py templates
  - acceptance: Given portals in the registry, when find_portals_from(iri) is called, then results come from a SPARQL SELECT executed against the store, not from a Python cache.
  - verifiedBy: src/holonic/test/test_portal.py::test_find_portals_uses_sparql

- R4.3 `traverse_portal(portal_iri)` MUST execute the portal's CONSTRUCT query against the quad store and MAY inject the result into a target named graph.
  - priority: MUST
  - constrains: HolonicDataset.traverse_portal
  - acceptance: Given a registered portal and inject_into=target_graph, when traverse_portal is called, then the CONSTRUCT's triples appear in the target graph and the CONSTRUCT result Graph is returned.
  - verifiedBy: src/holonic/test/test_portal.py::test_traverse_portal_injects_into_target

- R4.4 `traverse(source, target, validate=True)` MUST compose discovery, traversal, membrane validation, and provenance recording as one governed operation. Validation failure MUST NOT inject data into the target interior.
  - priority: MUST
  - constrains: HolonicDataset.traverse
  - acceptance: Given a boundary shape that rejects the source data, when traverse(source, target, validate=True) is called, then the target interior contains no new triples and the returned membrane result is Compromised.
  - verifiedBy: src/holonic/test/test_portal.py::test_governed_traverse_blocks_on_compromise

- R4.5 Multi-hop path finding (`find_path`) MUST run as a single SPARQL query over the registry/boundary graphs, not as Python BFS over pre-fetched portal lists.
  - priority: MUST
  - constrains: HolonicDataset.find_path, sparql.py
  - acceptance: Given a chain of three holons linked by portals, when find_path(source, target) is called, then one SPARQL SELECT returns the path and no Python iteration is involved.
  - verifiedBy: src/holonic/test/test_portal.py::test_find_path_single_sparql_query

## R5 Provenance

- R5.1 Every governed traversal and membrane validation MUST emit a `prov:Activity` into the target holon's context graph, including `prov:wasAssociatedWith`, `prov:used`, `prov:generated`, and `prov:startedAtTime`.
  - priority: MUST
  - constrains: HolonicDataset.traverse, HolonicDataset.record_traversal, HolonicDataset.record_validation
  - acceptance: Given traverse(source, target, agent_iri="urn:agent:x"), when the context graph is queried, then a prov:Activity exists with all four listed predicates populated.
  - verifiedBy: src/holonic/test/test_audit.py::test_traversal_writes_full_activity

- R5.2 Graph-to-graph derivation produced by a traversal (target interior derived from source interior) MUST use `prov:wasDerivedFrom` and MUST be distinct from `cga:derivedFrom`.
  - priority: MUST
  - constrains: HolonicDataset.traverse, cga.ttl
  - acceptance: Given a completed traversal, when the context graph is queried, then the target interior carries prov:wasDerivedFrom pointing to the source interior AND no cga:derivedFrom triple was created as a side effect.
  - verifiedBy: src/holonic/test/test_audit.py::test_prov_wasDerivedFrom_distinct_from_cga_derivedFrom

- R5.3 `cga:derivedFrom` MUST be reserved for persistent holon-to-holon structural dependency independent of any activity. The two properties coexist; neither replaces the other.
  - priority: MUST
  - constrains: cga.ttl, HolonicDataset.add_holon
  - acceptance: Given a holon declared with derived_from=other_holon, when the registry is queried, then cga:derivedFrom links the two holons AND no prov:Activity was created by the declaration alone.
  - verifiedBy: src/holonic/test/test_ontology.py::test_derivedFrom_semantics

- R5.4 `HolonSplit` and `HolonMerge` MUST be modeled as `prov:Activity` subclasses with `prov:used` (source holon) and `prov:generated` (resulting holons).
  - priority: MUST
  - constrains: cga.ttl
  - acceptance: Given a HolonSplit instance, when SPARQL queries its rdf:type chain, then prov:Activity appears in the class hierarchy and both prov:used and prov:generated are declared.
  - verifiedBy: src/holonic/test/test_ontology.py::test_split_merge_are_activity_subclasses

## R6 Console Model

- R6.1 The `holonic.console_model` module MUST expose dataclasses tuned for JSON serialization over HTTP: `HolonSummary`, `HolonDetail`, `ClassInstanceCount`, `NeighborhoodNode`, `NeighborhoodEdge`, `NeighborhoodGraph`, `PortalSummary`, `PortalDetail`.
  - priority: MUST
  - constrains: console_model.py
  - acceptance: Given each named dataclass, when round-tripped through dataclasses.asdict + json.dumps + json.loads, then no information is lost and no rdflib types leak.
  - verifiedBy: src/holonic/test/test_console_model.py::test_dataclasses_json_roundtrip

- R6.2 `NeighborhoodGraph.to_graphology()` MUST return a dict matching graphology's JSON shape so sigma.js can consume it without further transformation.
  - priority: MUST
  - constrains: NeighborhoodGraph.to_graphology
  - acceptance: Given a NeighborhoodGraph with nodes and edges, when to_graphology() is called, then the returned dict has top-level 'nodes' and 'edges' arrays with the key/attributes shape graphology expects.
  - verifiedBy: src/holonic/test/test_console_methods.py::test_to_graphology_shape

- R6.3 `HolonicDataset.list_holons_summary()` MUST return lightweight summaries via a single SPARQL query with no per-holon fan-out.
  - priority: MUST
  - constrains: HolonicDataset.list_holons_summary, sparql.py
  - acceptance: Given N holons in the registry, when list_holons_summary() is called, then exactly one SELECT query is issued against the store and N HolonSummary objects are returned.
  - verifiedBy: src/holonic/test/test_console_methods.py::test_list_holons_summary_single_query

- R6.4 `HolonicDataset.get_holon_detail(iri)` MUST return full layer IRIs plus interior triple count.
  - priority: MUST
  - constrains: HolonicDataset.get_holon_detail, HolonDetail
  - acceptance: Given a holon with two interior graphs, when get_holon_detail(iri) is called, then the returned HolonDetail lists both interior graph IRIs and interior_triple_count matches the actual triple sum.
  - verifiedBy: src/holonic/test/test_console_methods.py::test_get_holon_detail_completeness

- R6.5 `HolonicDataset.holon_interior_classes(iri)` MUST return `(class_iri, count)` pairs computed by SPARQL, not by Python iteration over triples.
  - priority: MUST
  - constrains: HolonicDataset.holon_interior_classes, sparql.py
  - acceptance: Given an interior with three distinct rdf:type values, when holon_interior_classes is called, then three ClassInstanceCount pairs come back from a single GROUP BY SPARQL query.
  - verifiedBy: src/holonic/test/test_console_methods.py::test_interior_classes_via_sparql

- R6.6 `HolonicDataset.holon_neighborhood(iri, depth=1)` MUST return a BFS subgraph bounded by portal topology, with `depth` clamped to a reasonable maximum to bound runaway traversals.
  - priority: MUST
  - constrains: HolonicDataset.holon_neighborhood
  - acceptance: Given depth=1000, when holon_neighborhood(iri, depth=1000) is called, then the library clamps to its internal cap (not 1000) and returns within expected time bounds.
  - verifiedBy: src/holonic/test/test_console_methods.py::test_neighborhood_depth_clamp

- R6.7 `HolonicDataset.portal_traversal_history(iri, limit=50)` MUST return recent `prov:Activity` records scoped to the portal, with `limit` clamped to 10,000.
  - priority: MUST
  - constrains: HolonicDataset.portal_traversal_history
  - acceptance: Given limit=50000, when portal_traversal_history is called, then at most 10000 records come back regardless of how many activities exist.
  - verifiedBy: src/holonic/test/test_console_methods.py::test_traversal_history_limit_clamp

## R7 Projections

- R7.1 Projection operations MUST support two modes: CONSTRUCT (result stays as RDF, storable in the holarchy) and Pythonic (result exits RDF into LPG-shaped dicts for visualization consumers).
  - priority: MUST
  - constrains: projections.py
  - acceptance: Given a source graph, when build_construct() returns a CONSTRUCT string AND project_to_lpg() returns a ProjectedGraph dict, then both modes are available and produce the documented shapes.
  - verifiedBy: src/holonic/test/test_projections.py::test_both_projection_modes_supported

- R7.2 `project_to_lpg(graph, ...)` MUST support four independent boolean flags controlling the core simplifications: `collapse_types`, `collapse_literals`, `resolve_blanks`, and `resolve_lists`. Each flag governs a distinct transformation (types→node annotations, literals→node attributes, blank nodes inlined as nested attributes, RDF lists resolved to Python lists) and each MUST be toggleable independently of the others.
  - priority: MUST
  - constrains: project_to_lpg
  - acceptance: Given a graph with all four RDF features, when project_to_lpg is called with each flag independently toggled, then each feature is transformed only when its corresponding flag is true.
  - verifiedBy: src/holonic/test/test_projections.py::test_project_to_lpg_flags_independent

- R7.3 `ProjectionPipeline` MUST compose named steps as a sequence of CONSTRUCT queries and Python transforms, with `.apply_to_lpg()` and `.apply_to_graph()` terminal methods.
  - priority: MUST
  - constrains: ProjectionPipeline
  - acceptance: Given a pipeline of two CONSTRUCT steps and one transform, when apply_to_graph() is called, then steps run in the declared order and the result reflects all three transformations.
  - verifiedBy: src/holonic/test/test_projections.py::test_pipeline_composition_order

- R7.4 `project_holon(iri, store_as=...)` MUST merge all interior graphs, apply the pipeline, and optionally write the result back to a named graph.
  - priority: MUST
  - constrains: HolonicDataset.project_holon
  - acceptance: Given a holon with two interiors, when project_holon(iri, store_as="urn:out") is called, then the output graph contains triples derived from both interiors and is registered as a cga:hasProjection layer.
  - verifiedBy: src/holonic/test/test_client_projections.py::test_project_holon_merges_and_stores

- R7.5 `project_holarchy()` MUST project the topology (holons as nodes, portals and `cga:memberOf` as edges) into an LPG.
  - priority: MUST
  - constrains: HolonicDataset.project_holarchy
  - acceptance: Given a holarchy with three holons and two portals and one memberOf relation, when project_holarchy() is called, then the resulting ProjectedGraph has three nodes and three edges.
  - verifiedBy: src/holonic/test/test_client_projections.py::test_project_holarchy_topology

## R8 Testing and Distribution

- R8.1 The default pytest suite MUST pass against `RdflibBackend` with no external services.
  - priority: MUST
  - constrains: src/holonic/test/
  - acceptance: Given a clean environment with base install only, when `pytest src/holonic/test/` is run, then every test passes or is skipped with a declared marker like @pytest.mark.fuseki.
  - verifiedBy: src/holonic/test/ (full suite, 272 passing)

- R8.2 Fuseki integration tests, if any, MUST be marked with `@pytest.mark.fuseki` and skipped when Fuseki is unavailable.
  - priority: MUST
  - constrains: test_console_methods.py, pyproject.toml pytest config
  - acceptance: Given no Fuseki server, when pytest runs, then Fuseki-tagged tests are skipped rather than errored.
  - verifiedBy: pyproject.toml markers + src/holonic/test/test_console_methods.py usage of importorskip

- R8.3 Test fixtures MUST use Turtle loaded via `backend.parse_into()` rather than programmatic rdflib graph construction.
  - priority: MUST
  - constrains: src/holonic/test/, STYLE_GUIDE.md
  - acceptance: Given the test suite, when grepped for Graph().add((URIRef, URIRef, ...)) patterns, then no production test uses that programmatic style for fixture data; all fixtures are Turtle.
  - verifiedBy: src/holonic/test/ (convention enforced by STYLE_GUIDE.md)

- R8.4 The package MUST publish to PyPI under `holonic` and be installable with `pip install holonic`.
  - priority: MUST
  - constrains: pyproject.toml, release workflow
  - acceptance: Given a clean virtualenv, when `pip install holonic` is run, then the package installs from PyPI and `python -c "import holonic"` succeeds.
  - verifiedBy: .github/workflows/release.yml (manual verification at tag time)

- R8.5 Optional extras (`dev`, `docs`, `entailment`, `fuseki`, `lint`, `notebooks`, `test`, `viz`) MUST keep the base install under five seconds on a typical network.
  - priority: SHOULD
  - constrains: pyproject.toml optional-dependencies
  - acceptance: Given a clean virtualenv, when `pip install holonic` is timed, then installation completes in under five seconds on a 50 Mbps connection.
  - verifiedBy: manual timing at release rehearsal

## R9 Next Evolution

### Shipped in 0.3.3

- R9.1 The registry SHOULD carry graph-level operational metadata per layer graph: triple count, last-modified timestamp, and materialized class inventory. `HolonicDataset.refresh_metadata()`, `refresh_all_metadata()`, and `get_graph_metadata()` provide the read/write surface. Shipped with `metadata_updates="eager"|"off"` policy.
  - priority: SHOULD
  - constrains: HolonicDataset, MetadataRefresher, cga.ttl
  - acceptance: Given a holon with one interior graph, when add_interior runs in eager mode, then get_graph_metadata returns a GraphMetadata with triple_count equal to the parsed count and last_modified within the last second.
  - verifiedBy: src/holonic/test/test_metadata.py::test_eager_metadata_on_interior_write

- R9.2 The CGA ontology MUST declare graph-level metadata vocabulary (`cga:ClassInstanceCount` class; `cga:tripleCount`, `cga:lastModified`, `cga:refreshedAt`, `cga:inGraph`, `cga:class`, `cga:count`, `cga:holonLastModified` properties).
  - priority: MUST
  - constrains: cga.ttl section 7
  - acceptance: Given cga.ttl, when SPARQL queries the listed IRIs, then all are declared with appropriate rdfs:domain and rdfs:range.
  - verifiedBy: src/holonic/test/test_ontology.py::test_section_7_vocabulary_present

### Shipped in 0.3.4

- R9.3 The CGA ontology MUST declare graph-category vocabulary so named graphs carry RDF types discoverable via SPARQL. Implemented as the flat+role pattern: `cga:HolonicGraph` class plus `cga:graphRole` object property ranged over `cga:LayerRole` individuals. New individual `cga:RegistryRole` covers the cross-cutting registry graph. See `docs/DECISIONS.md` § D-0.3.4-1.
  - priority: MUST
  - constrains: cga.ttl section 8
  - acceptance: Given add_interior("urn:h"), when the registry is queried, then the interior graph is declared as cga:HolonicGraph with cga:graphRole cga:InteriorRole.
  - verifiedBy: src/holonic/test/test_typed_graphs.py::test_interior_graph_typed_on_registration

- R9.4 The library MUST add a `resolve(predicate, from_holon, max_depth, order, limit)` method implementing decreasing-priority scope resolution across the holarchy. `HolonicDataset.resolve()` in `holonic.scope`. Two predicate classes shipped: `HasClassInInterior` (uses 0.3.3 class inventory) and `CustomSPARQL` (escape hatch). Three ordering modes: `"network"` (default, outbound+inbound portals), `"reverse-network"`, `"containment"`. Strict BFS topology.
  - priority: MUST
  - constrains: holonic.scope, HolonicDataset.resolve
  - acceptance: Given a linear chain of four holons with a target class in the last holon, when resolve(HasClassInInterior(cls), from_holon=first, max_depth=3) is called, then the last holon is returned with distance=3.
  - verifiedBy: src/holonic/test/test_scope.py::test_has_class_in_interior_linear_chain

- R9.5 The library MUST ship a migration CLI to backfill graph-type declarations for pre-0.3.4 deployments. `holonic-migrate-registry` entry point, idempotent, dry-run by default.
  - priority: MUST
  - constrains: holonic.cli.migrate_registry
  - acceptance: Given a pre-0.3.4 registry without cga:HolonicGraph type declarations, when `holonic-migrate-registry --apply` is run, then every layer graph gains its type; a second invocation is a no-op.
  - verifiedBy: src/holonic/test/test_typed_graphs.py::test_migration_cli_idempotent

### Shipped in 0.3.5

- R9.6 The library MUST ship a projection plugin system. Projection pipelines are RDF-modeled specs (`cga:ProjectionPipelineSpec`) in the registry graph, carrying an `rdf:List` of `cga:ProjectionPipelineStep` entries. Python transforms are discovered via the `holonic.projections` entry-point group (both first-party and third-party). Pipelines reference transforms by registered name; registration validates name resolution.
  - priority: MUST
  - constrains: holonic.plugins, HolonicDataset.register_pipeline, cga.ttl section 9
  - acceptance: Given a ProjectionPipelineSpec with one step referencing transform "strip_blank_nodes", when register_pipeline(spec) is called, then the spec is written to the registry as cga:ProjectionPipelineSpec and the transform is resolved via the entry-point registry.
  - verifiedBy: src/holonic/test/test_plugins.py::test_register_pipeline_validates_transform_names

- R9.7 The library MUST ship `HolonicDataset.register_pipeline()`, `attach_pipeline()`, `list_pipelines()`, `get_pipeline()`, and `run_projection()`. Running a pipeline emits a `prov:Activity` in the target holon's context graph with loose version tracking (`cga:transformVersion`) and host metadata (`cga:runHost`, `cga:runPlatform`, `cga:runPythonVersion`, `cga:runHolonicVersion`). Running with `store_as` refreshes metadata on the output graph per D-0.3.3-5.
  - priority: MUST
  - constrains: HolonicDataset, holonic.plugins.host_metadata
  - acceptance: Given a registered pipeline attached to a holon, when run_projection(holon, spec, store_as=out) is called, then a prov:Activity appears in the holon's context graph with all four cga:run* host metadata predicates populated.
  - verifiedBy: src/holonic/test/test_plugins.py::test_run_projection_records_provenance

### Shipped in 0.4.0

- R9.8 The backend protocol MUST split into a mandatory core and an optional mixin. Implemented as `HolonicStore` (Protocol, mandatory) + `AbstractHolonicStore` (ABC, recommended base with hook points for optional methods). Backends declaring only the Protocol surface continue to work via the library's Python-fallback helpers. Optional native methods are dispatched via `hasattr`. The initial optional surface is a single method: `refresh_graph_metadata(graph_iri, registry_iri)`.
  - priority: MUST
  - constrains: holonic.backends.store, MetadataRefresher
  - acceptance: Given a store with a refresh_graph_metadata method, when MetadataRefresher.refresh_graph runs, then the native method is invoked; given a store without it, the Python fallback runs instead.
  - verifiedBy: src/holonic/test/test_deprecation_and_dispatch.py::test_metadata_refresher_dispatches_to_native

- R9.9 The library MUST preserve `GraphBackend` as a deprecated alias through the 0.4.x series and provide a migration guide (`docs/MIGRATION.md`). Deprecation warnings are suppressible via `HOLONIC_SILENCE_DEPRECATION=1`.
  - priority: MUST
  - constrains: holonic/__init__.py, holonic/backends/__init__.py, holonic/backends/protocol.py
  - acceptance: Given `from holonic import GraphBackend`, when executed without HOLONIC_SILENCE_DEPRECATION, then a DeprecationWarning is emitted and the alias resolves to HolonicStore.
  - verifiedBy: src/holonic/test/test_deprecation_and_dispatch.py::test_graphbackend_importable_from_holonic

- R9.10 The `HolonicDataset` constructor parameter previously named `registry_graph` MUST be renamed to `registry_iri` for consistency with internal usage. The old name remains as a deprecated alias through 0.4.x.
  - priority: MUST
  - constrains: HolonicDataset.__init__
  - acceptance: Given HolonicDataset(registry_graph="urn:r"), when the constructor runs, then a DeprecationWarning is emitted AND ds.registry_iri equals "urn:r".
  - verifiedBy: src/holonic/test/test_deprecation_and_dispatch.py::test_registry_graph_kwarg_still_works

### Remaining for 0.4.x / 0.5.0

- R9.11 The library SHOULD ship a `holonic.generators` module formalizing the existing `examples/` holarchy generators (company, research lab, random).
  - priority: SHOULD
  - constrains: holonic.generators (new module)
  - acceptance: Given `from holonic.generators import company_holarchy`, when the generator is invoked with a seed, then a deterministic holarchy with documented structure is produced against any HolonicStore.
  - verifiedBy: (pending implementation)

- R9.12 The library SHOULD offer a `metadata_updates="lazy"` mode (dirty tracking with `flush_metadata()`) if evidence emerges that eager and off modes leave a practical gap.
  - priority: SHOULD
  - constrains: HolonicDataset, MetadataRefresher
  - acceptance: Given HolonicDataset(metadata_updates="lazy"), when multiple writes occur followed by flush_metadata(), then metadata reflects the final state without per-write overhead.
  - verifiedBy: (pending implementation, gated on evidence from downstream usage)

- R9.13 The registry SHOULD optionally aggregate per-holon membrane health for fast dashboards and scope-resolution health predicates. Semantics and invalidation rules to be decided before implementation.
  - priority: SHOULD
  - constrains: cga.ttl, HolonicDataset, registry schema
  - acceptance: Given a holarchy with recent membrane validations, when the registry is queried for aggregated health, then per-holon rollup values are returned without recomputation from scratch.
  - verifiedBy: (pending implementation; design in open question OQ4)

- R9.14 The scope resolver SHOULD gain additional predicate classes (`HasPortalProducing`, `HasShapeFor`, `LabelMatches`) if evidence emerges that `CustomSPARQL` is being used as a workaround for missing first-class predicates.
  - priority: SHOULD
  - constrains: holonic.scope
  - acceptance: Given usage data showing CustomSPARQL patterns for portal/shape/label matching, when the named predicate classes ship, then the CustomSPARQL workarounds become first-class.
  - verifiedBy: (pending implementation, gated on usage evidence)

- R9.15 The library SHOULD ship a migration pass that synthesizes minimal `cga:ProjectionPipelineSpec` resources for projection graphs registered before 0.3.5, so historical projections get consistent provenance.
  - priority: SHOULD
  - constrains: holonic.cli.migrate_projections (new CLI)
  - acceptance: Given a pre-0.3.5 registry with projection layer graphs but no pipeline specs, when the migration CLI is run, then a minimal ProjectionPipelineSpec is synthesized for each projection and attached via cga:hasPipeline.
  - verifiedBy: (pending implementation)

- R9.16 Pipeline steps SHOULD support per-step arguments (e.g. `filter_by_class(class_iri)`) via a `cga:stepArguments` JSON literal or structured argument record.
  - priority: SHOULD
  - constrains: ProjectionPipelineStep, cga.ttl
  - acceptance: Given a pipeline step with transform_name="filter_by_class" and arguments={"class_iri": "urn:ex:Widget"}, when run_projection executes, then the transform receives the arguments as keyword args.
  - verifiedBy: (pending implementation)

- R9.17 The optional protocol surface SHOULD grow additively during 0.4.x with native hooks for scope walking, bulk load, and pipeline execution as backend-specific optimization opportunities arise.
  - priority: SHOULD
  - constrains: holonic.backends.store, AbstractHolonicStore
  - acceptance: Given a backend implementing an optional method like `walk_neighbors_native`, when the corresponding library helper dispatches, then `hasattr`-based detection invokes the native method without regressing duck-typed backends.
  - verifiedBy: (pending per-method implementation, following the refresh_graph_metadata precedent from R9.8)

- R9.18 In 0.5.0, the `GraphBackend` alias MUST be removed along with the `registry_graph` kwarg and `ds.registry_graph` property.
  - priority: MUST
  - constrains: holonic/__init__.py, holonic/backends/__init__.py, holonic/backends/protocol.py, HolonicDataset
  - acceptance: Given holonic 0.5.0 installed, when code imports GraphBackend or passes registry_graph=, then an ImportError or TypeError is raised respectively.
  - verifiedBy: (pending 0.5.0 release; test added at removal time)

### Shipped in 0.4.1

- R9.19 The library MUST ship a JupyterLite static build of the example notebooks for in-browser exploration without local Python installation. Build integrates with the existing `notebooks/` directory via `scripts/sync_notebooks_to_jlite.py`; output lands in `docs/source/_static/jupyterlite/` so Sphinx (and ReadTheDocs) serve it under the documentation domain. Notebook 11 (yFiles visualization) is excluded from in-browser execution because yFiles requires a Jupyter server extension that Pyodide cannot provide; the landing notebook `00_start_here.ipynb` documents this constraint.
  - priority: MUST
  - constrains: jupyterlite/, scripts/sync_notebooks_to_jlite.py, .readthedocs.yaml, pixi.toml (tasks-jlite), docs/source/_static/jupyterlite/
  - acceptance: Given the 0.4.1 release on ReadTheDocs, when a reader opens the docs and follows the "Try in browser" link, then the JupyterLite lab loads and notebooks 01-10 execute against a Pyodide kernel without local Python installation.
  - verifiedBy: docs/source/index.md "Try in browser" section + .readthedocs.yaml pre_build hooks + manual verification during release rehearsal

### Shipped in 0.4.2

- R9.20 The library MUST provide `HolonicDataset.remove_holon(iri)` completing the CRUD lifecycle started by `add_holon()`. Cleans up the holon's registry entry, all four layer graphs (interior/boundary/projection/context), graph-typing triples, graph-level metadata records, the per-holon rollup, and cascades to `remove_portal()` for every portal where the holon is source or target. Child holons that reference the removed holon via `cga:memberOf` are orphaned (their `memberOf` triple is removed) but not themselves deleted. Idempotent — returns `False` for a non-existent IRI rather than raising. Provenance activities referencing the removed holon are preserved because provenance is immutable history.
  - priority: MUST
  - constrains: HolonicDataset.remove_holon, holonic/client.py
  - acceptance: Given a holon with interior, boundary, and context layer graphs, plus a portal from it and a portal to it, plus a child holon referencing it as `cga:memberOf`, when `remove_holon(iri)` is called, then the holon is gone from `list_holons()`, all four layer graphs are deleted via `backend.graph_exists()=False`, both portals are gone from `find_portals_from`/`find_portals_to`, and the child remains in `list_holons()` but without its `memberOf` triple.
  - verifiedBy: src/holonic/test/test_lifecycle.py::TestRemoveHolon

- R9.21 The library MUST provide `HolonicDataset.remove_portal(portal_iri)` completing the CRUD lifecycle started by `add_portal()`. Removes all triples with `portal_iri` as subject from every graph containing them (typically the source holon's boundary graph and the registry mirror). The boundary graph itself is preserved — sibling portals and SHACL shapes in the same graph are unaffected. Idempotent — returns `False` for a non-existent portal IRI rather than raising. Metadata refresh fires per affected graph when `metadata_updates="eager"`.
  - priority: MUST
  - constrains: HolonicDataset.remove_portal, holonic/client.py
  - acceptance: Given a source holon with two portals declared in the same boundary graph plus a SHACL shape, when `remove_portal(portal_a)` is called, then portal_a is absent from `find_portals_from(source)`, portal_b is still discoverable, and the SHACL shape is still present in the boundary graph.
  - verifiedBy: src/holonic/test/test_lifecycle.py::TestRemovePortal

- R9.22 The `add_portal()` method MUST support creation of all portal subtypes declared in the CGA ontology (`cga:TransformPortal`, `cga:IconPortal`, `cga:SealedPortal`) as well as downstream subclasses via three additive parameters: `construct_query` is optional (default `None`); `portal_type` is a customizable RDF type (default `"cga:TransformPortal"`); `extra_ttl` accepts additional Turtle triples for predicates carried by downstream portal subclasses. All existing positional calls continue to work unchanged. Portal discovery (`find_portals_from/to/direct`) MUST match any portal subtype — the pre-0.4.2 hardcoded filter on `cga:TransformPortal` is relaxed because the `cga:sourceHolon` + `cga:targetHolon` predicate pair uniquely identifies a portal regardless of its specific subtype. Discovery queries use `SELECT DISTINCT` to deduplicate results across the boundary graph and registry mirror. The CGA ontology ships `cga:IconPortal` (previously undeclared) and SHACL shapes (`cga:IconPortalShape`, `cga:SealedPortalShape`) that warn when these subtypes carry `cga:constructQuery`; `cga:TransformPortalShape` continues to require exactly one `cga:constructQuery`.
  - priority: MUST
  - constrains: HolonicDataset.add_portal, holonic/client.py, holonic/sparql.py (FIND_PORTALS_FROM, FIND_PORTALS_TO, FIND_PORTAL_DIRECT), holonic/ontology/cga.ttl (cga:IconPortal), holonic/ontology/cga-shapes.ttl (cga:IconPortalShape, cga:SealedPortalShape)
  - acceptance: Given a portal created with `portal_type="cga:SealedPortal"` and no `construct_query`, when `find_portals_from(source)` is called, then exactly one `PortalInfo` is returned with `construct_query=None`; and given a portal created with `extra_ttl` carrying a downstream predicate, when the boundary graph is queried by SPARQL for that predicate, then the extra triples are present; and given a TransformPortal without a constructQuery or a SealedPortal/IconPortal carrying one, when the registry is validated against `cga-shapes.ttl`, then the corresponding shape reports a violation (for TransformPortal) or warning (for SealedPortal and IconPortal).
  - verifiedBy: src/holonic/test/test_lifecycle.py::TestAddPortalExtensibility and src/holonic/test/test_ontology.py::TestPortalSubtypeShapeSemantics

# User Stories

- US1 As a knowledge engineer, I create a holon, add interior data from multiple sources into named sub-graphs, declare boundary shapes, and validate the membrane — all from a single `HolonicDataset` instance against in-memory rdflib.
  - asA: knowledge engineer
  - soThat: I can enforce structural contracts on holon interior data without standing up external infrastructure
  - acceptance: Given HolonicDataset() with an in-memory backend, when I create a holon with two interiors and a boundary shape and call validate_membrane, then I receive a MembraneResult with health and violation details.

- US2 As a systems integrator, I register a portal between two holons with a CONSTRUCT query that translates one vocabulary to another, traverse it, and see the target interior populated only when the membrane validates.
  - asA: systems integrator
  - soThat: vocabulary translation between holons is governed rather than ad-hoc
  - acceptance: Given a source holon with CCO-shaped data and a target holon with Schema.org boundary shapes, when I register a CONSTRUCT portal and call traverse(source, target, validate=True), then Schema.org triples appear in the target only if validation passes.

- US3 As an operator-tool builder, I use `list_holons_summary()`, `holon_neighborhood(iri, depth=2)`, and `to_graphology()` to render a sigma.js graph of the holarchy in a web console without any custom SPARQL.
  - asA: operator-tool builder
  - soThat: I can ship a working web console without writing SPARQL in my frontend code
  - acceptance: Given a populated holarchy, when I call list_holons_summary() and holon_neighborhood(iri, depth=2).to_graphology(), then the returned dicts deserialize to JSON suitable for direct sigma.js consumption.

- US4 As a platform engineer, I deploy against Fuseki with bearer-token auth by passing `extra_headers={"Authorization": "Bearer ..."}` to `FusekiBackend` and the library transparently authenticates every SPARQL request.
  - asA: platform engineer
  - soThat: secrets-based authentication flows through to the SPARQL endpoint without library modifications
  - acceptance: Given FusekiBackend(url, dataset=ds, extra_headers={"Authorization": "Bearer x"}), when any SPARQL request is issued, then the Authorization header reaches the server unchanged.

- US5 As an agent author, I use portal traversal as an agentic memory write path: each agent turn runs through a portal with SHACL shape validation, and every turn produces a PROV-O record linking agent, input, output, and activity time.
  - asA: agent author
  - soThat: agent memory writes are validated and auditable end-to-end
  - acceptance: Given an agent iterating through a governed portal with validate=True, when a turn completes, then the context graph contains a prov:Activity with prov:wasAssociatedWith the agent, prov:used the input, prov:generated the output, and prov:startedAtTime the turn timestamp.

- US6 As a data steward, I query the context graph across all holons in a holarchy and receive an audit trail of traversals with membrane health, agent attribution, and timestamps.
  - asA: data steward
  - soThat: I can produce a complete activity record for compliance review
  - acceptance: Given a holarchy with traversal history, when I run a SPARQL query over the union of context graphs, then I receive activity, agent, input, output, timestamp, and membrane health for every governed operation.

- US7 As a spec author, I translate this SPEC to Turtle via `specl-translate`, validate it against the shipped SHACL shapes, and publish a maturity badge in the README.
  - asA: spec author
  - soThat: spec quality is machine-measurable and visible to external consumers
  - acceptance: Given docs/SPEC.md, when specl-translate and specl-validate score are run, then a maturity percentage and SVG badge artifact are produced and the spec's structural integrity is asserted by SHACL.

# Design Considerations

- The dataset is the holarchy. Python methods are convenience over SPARQL, not a separate object model. Dataclasses returned from queries are ephemeral views, not persistent state.
- Named graphs are hypergraphs. Recognizing this subsumes the RDF-vs-LPG distinction and makes the four-graph model a natural consequence of standard RDF 1.1 semantics.
- SPARQL is the primary control surface. Python handles only what SPARQL cannot express (Dijkstra path ranking, template rendering, pipeline orchestration).
- Minimal dependencies. The hard deps are rdflib, pyshacl, and pydantic. Optional extras add jupyter, aiohttp (Fuseki), owlrl (entailment), and visualization widgets.
- PROV-O for activity-level provenance. Graph-to-graph derivation via `prov:wasDerivedFrom`. Holon-to-holon structural dependency via `cga:derivedFrom`. These are distinct concepts and both exist.
- SHACL shapes, not OWL axioms, for constraint checking. Reasoner-free by design; entailment is optional via the `owlrl` extra.
- Nested Turtle notation everywhere the library emits RDF. Predicates grouped with `;`, object lists with `,`. No verbose explicit-triple form in examples, fixtures, or docs.

# Comments

- The four layers (interior, boundary, projection, context) are explicit in the ontology as `cga:LayerRole` individuals (`cga:InteriorRole`, `cga:BoundaryRole`, `cga:ProjectionRole`, `cga:ContextRole`) and as bridging properties (`cga:hasInterior` etc. as sub-properties of `cga:hasLayer`). The model accommodates multiple graphs per role.
- The registry graph (`urn:holarchy:registry`) in R9 proposals refers to a cross-cutting catalog graph for holarchy-level declarations. It is distinct from per-holon layer graphs and is declared at the holarchy level, not the holon level.
- `holonic-console` is the primary downstream consumer driving the 0.3.1 API additions. Its stage 2 work (sigma.js neighborhood view, portal browser, provenance feed) is the functional proof for R6.
- `specl` provides the SHACL validation of this SPEC itself. The spec is dogfood: the library under development is specified using a tool whose ontology was co-designed with it.
- Cagle's "The Graph as State Machine" (*The Inference Engineer*, April 2026) frames a holonic graph as a graph-level state machine where the four layers map to Scene / Boundary / Event / Projection and `sh:SPARQLRule` is the transition function driven by a clock-triggered tick. The library today implements the four layers structurally but operates event-triggered (portal traversals invoked by callers) rather than clock-triggered. Whether to add a tick primitive is captured as OQ8.

# Open Questions and Gaps (flag for follow-up)

- OQ1 Registry-graph typing vs holon-graph-as-holon. If typed graphs (R9.1) are adopted, should the registry graph itself be typed as `cga:RegistryGraph`, and should it be modeled as the interior of a `RegistryHolon`? Bootstrapping implications unresolved.
  - owner: zwelz3
  - recommendation: Type the registry graph explicitly as cga:RegistryRole (shipped in 0.3.4); defer the registry-as-holon question until after R9.1 ships.
  - status: resolved

- OQ2 Subclass vs flat+roles for graph categories. `cga:InteriorGraph rdfs:subClassOf cga:HolonicGraph` versus `?g a cga:HolonicGraph ; cga:graphRole cga:InteriorRole`. Subclass is terser in queries; flat+roles supports multi-role graphs cleanly (e.g. a graph that is both an interior and a provenance aggregate).
  - owner: zwelz3
  - recommendation: Adopt flat+roles because the dual-role case is real (see cga:AggregateHolon); cost is one extra triple pattern per query. Shipped in 0.3.4 via D-0.3.4-1.
  - status: resolved

- OQ3 Scope resolution ordering configurability. The proposed order (self → portal neighbors → siblings → parent → wider) serves network-proximity queries. Containment-first ordering serves governance queries. Reverse portal distance serves debugging queries.
  - owner: zwelz3
  - recommendation: Default to network-proximity; accept an order= parameter on resolve() taking a strategy enum. Shipped in 0.3.4 with three modes: network, reverse-network, containment.
  - status: resolved

- OQ4 Class-inventory staleness strategy. Materialized inventory in the registry needs a refresh policy: synchronous (slow writes), asynchronous (fast writes, stale reads), on-demand (explicit refresh), or TTL-based (configurable staleness).
  - owner: zwelz3
  - recommendation: Per-HolonicDataset strategy at construction time. Shipped in 0.3.3 with eager and off modes; lazy mode deferred to R9.12 gated on usage evidence.
  - status: in-review

- OQ5 Graph-level metadata write amplification. If every portal traversal updates `cga:interiorTripleCount` and last-modified in the registry, write amplification dominates in high-throughput pipelines.
  - owner: zwelz3
  - recommendation: Make metadata updates opt-in via a constructor kwarg. Shipped in 0.3.3 as metadata_updates="eager"|"off" on HolonicDataset.
  - status: resolved

- OQ6 Protocol rename (`GraphBackend` to `HolonicStore`) remains unresolved from issue #4 Option D.
  - owner: zwelz3
  - recommendation: Ship the rename in 0.4.0 as a breaking change with a deprecated alias kept through 0.4.x. Shipped via R9.8, R9.9.
  - status: resolved

- OQ7 Federation semantics across multiple registries are out of scope for 0.3.x. Open question preserved because the typed-graph design (R9.1) should not close the door on registry-to-registry declarations like `cga:federatesWith`.
  - owner: zwelz3
  - recommendation: Defer to 0.5.0 design session; ensure R9.3's typed-graph vocabulary leaves room for a future federation property without schema migration.
  - status: deferred

- OQ8 Graph-level tick semantics and transition rules. Cagle's "The Graph as State Machine" (*The Inference Engineer*, April 2026) frames a holonic graph as a graph-level state machine in the Game-of-Life sense: Scene Graph (interior state), Boundary Graph (SHACL rules including `sh:SPARQLRule` transition functions), Event Graph (PROV-O transition history), and Projection Graph (external observation). The library implements all four layers structurally but does not implement a tick — portal traversals are event-triggered rather than clock-triggered, and SHACL is used for validation rather than for `$this`-based transformation rules. A future `HolonicDataset.tick()` primitive could fire SHACL transition rules across the whole holarchy, either accumulating PROV-O activities into the Event Graph or mutating the Scene Graph directly via SPARQL UPDATE. Whether to add this is a distinct architectural question from anything currently in the roadmap; adopting it would extend the library from a read-heavy, portal-triggered coordination layer into a living-system model with continuous dynamics.
  - owner: zwelz3
  - recommendation: Wait for Part 2 of the Cagle series (Active Inference / Free Energy Principle) to land before committing to a tick API. Evaluate whether a tick is the right primitive or whether something finer-grained (an active-inference step, an energy-minimization iteration) is more apt. If pursued at all, target a `holonic.contrib` experimental module first to test the pattern without committing the core ontology. No release slot assigned; this may or may not be implemented.
  - status: deferred

- OQ9 DOM-style event propagation as a coordination model. Cagle proposes (LinkedIn thread, April 2026) that plural-orchestrator coordination can be resolved by treating the holarchy as a structure over which events propagate in the W3C Document Object Model's capture/target/bubble pattern. Under this framing: the containing holon makes no expectations on child interiors (opacity is first-class); external events arrive at a holon and are either consumed, delegated to children via portals, or ignored after propagation completes; "eventually ignored" is a legitimate outcome rather than a failure mode. This is distinct from OQ8's tick proposal — event propagation is structural (who receives an event depends on the containment topology) rather than clock-triggered. The library today implements something DOM-adjacent via portal traversal and multi-hop path finding, but does not expose explicit event-dispatch semantics. Open questions surface immediately when mapping DOM to holons: DOM events are synchronous and the DOM is a strict tree, whereas a federated holarchy is asynchronous and a containment graph may have multiple portal paths between two holons. Whether to adopt the DOM framing as library architecture, as a mental model for explaining existing capabilities, or neither, remains open.
  - owner: zwelz3
  - recommendation: Before any implementation, verify whether the existing portal-traversal API strains under real use cases that DOM-style event dispatch would address more naturally. If strain emerges, the design question becomes: extend existing portal semantics with explicit event-phase hooks (capture/target/bubble), add a dedicated `dispatch_event` API parallel to `traverse`, or adopt the DOM model as framing while keeping the current API unchanged. The documentation at `docs/source/dom-comparison.md` establishes the mental-model mapping without committing to implementation. No release slot assigned; this may or may not be implemented.
  - status: deferred

# Appendix A: Suggested Namespaces

```turtle
@prefix cga:     <urn:holonic:ontology:> .
@prefix prov:    <http://www.w3.org/ns/prov#> .
@prefix sh:      <http://www.w3.org/ns/shacl#> .
@prefix owl:     <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:    <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix schema:  <https://schema.org/> .
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
```

# Appendix B: Module Map (0.3.1)

```
src/holonic/
├── __init__.py            re-exports HolonicDataset, models, ontology loaders
├── client.py              HolonicDataset — the primary API surface
├── model.py               HolonInfo, PortalInfo, MembraneResult, AuditTrail, SurfaceReport
├── console_model.py       HolonSummary, HolonDetail, NeighborhoodGraph, PortalSummary, ...
├── sparql.py              SPARQL templates as named string constants
├── projections.py         CONSTRUCT_STRIP_TYPES, project_to_lpg, ProjectionPipeline
├── backends/
│   ├── protocol.py        GraphBackend protocol
│   ├── rdflib_backend.py  in-memory rdflib.Dataset backend
│   ├── fuseki_backend.py  Apache Jena Fuseki HTTP backend
│   └── _fuseki_client.py  low-level HTTP helpers
├── ontology/
│   ├── cga.ttl            CGA ontology (holons, portals, layers, governance)
│   └── cga-shapes.ttl     SHACL shapes (membrane validation scaffolding)
├── viz/
│   ├── graph_builder.py   build visualization-ready graph structures
│   ├── formatters.py      text/table formatters
│   ├── provenance.py      provenance visualization helpers
│   ├── styles.py          color/shape palettes
│   └── widgets.py         ipywidgets composite displays
└── test/                  pytest suite (all run against RdflibBackend)
```
