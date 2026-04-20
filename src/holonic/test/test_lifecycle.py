"""Tests for structural lifecycle methods added in 0.4.2.

Covers:

- ``HolonicDataset.remove_holon(iri)``
- ``HolonicDataset.remove_portal(portal_iri)``
- Extended ``add_portal()`` signature (optional ``construct_query``,
  ``portal_type``, ``extra_ttl``)
"""

import pytest

from holonic import HolonicDataset, RdflibBackend


# ══════════════════════════════════════════════════════════════
# Change 3 — extensible add_portal()
# ══════════════════════════════════════════════════════════════


class TestAddPortalExtensibility:
    """Portal creation with optional query + custom type + extra triples."""

    def test_add_portal_without_construct_query(self, ds):
        """construct_query=None produces a portal with no cga:constructQuery."""
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B")
        ds.add_portal(
            "urn:portal:a-to-b",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            construct_query=None,
        )
        portals = ds.find_portals_from("urn:holon:a")
        assert len(portals) == 1
        assert portals[0].iri == "urn:portal:a-to-b"
        assert portals[0].construct_query is None

    def test_add_portal_with_sealed_type(self, ds):
        """portal_type overrides the default cga:TransformPortal."""
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B")
        ds.add_portal(
            "urn:portal:sealed",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            portal_type="cga:SealedPortal",
        )
        # Verify the type triple
        rows = list(ds.query(
            """
            PREFIX cga: <urn:holonic:ontology:>
            SELECT (COUNT(*) AS ?n) WHERE {
                GRAPH ?g {
                    <urn:portal:sealed> a cga:SealedPortal .
                }
            }
            """
        ))
        assert rows and int(rows[0]["n"]) > 0

    def test_add_portal_with_extra_ttl(self, ds):
        """extra_ttl predicates land in both the boundary graph and registry."""
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B")
        ds.add_portal(
            "urn:portal:custom",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            portal_type="ext:CustomPortal",
            extra_ttl="""
                @prefix ext: <urn:ext:> .
                <urn:portal:custom> ext:weight "0.87"^^<http://www.w3.org/2001/XMLSchema#decimal> ;
                    ext:transformRef <urn:model:v1> .
            """,
        )

        # Extra triples reachable via SPARQL in the boundary graph
        boundary_rows = list(ds.query(
            """
            PREFIX ext: <urn:ext:>
            SELECT ?ref WHERE {
                GRAPH <urn:holon:a/boundary> {
                    <urn:portal:custom> ext:transformRef ?ref .
                }
            }
            """
        ))
        assert len(boundary_rows) == 1
        assert str(boundary_rows[0]["ref"]) == "urn:model:v1"

        # Also mirrored in the registry
        registry_rows = list(ds.query(
            """
            PREFIX ext: <urn:ext:>
            SELECT ?ref WHERE {
                GRAPH <urn:holarchy:registry> {
                    <urn:portal:custom> ext:transformRef ?ref .
                }
            }
            """
        ))
        assert len(registry_rows) == 1

    def test_existing_positional_call_still_works(self, ds):
        """The 0.3.x/0.4.0 positional construct_query call is unchanged."""
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B")
        ds.add_portal(
            "urn:portal:legacy",
            "urn:holon:a",
            "urn:holon:b",
            "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
        )
        portals = ds.find_portals_from("urn:holon:a")
        assert len(portals) == 1
        assert portals[0].construct_query is not None


# ══════════════════════════════════════════════════════════════
# Change 2 — remove_portal()
# ══════════════════════════════════════════════════════════════


class TestRemovePortal:
    """Portal lifecycle: safe removal without touching other portals."""

    def _setup_two_portals(self, ds):
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B")
        ds.add_holon("urn:holon:c", "C")
        # Two SHACL shapes in the source boundary graph, so we can
        # prove the boundary graph survives portal removal.
        ds.add_boundary(
            "urn:holon:a",
            """
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            <urn:shapes:One> a sh:NodeShape ;
                sh:targetClass <urn:type:One> .
            """,
        )
        ds.add_portal(
            "urn:portal:a-to-b",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
        )
        ds.add_portal(
            "urn:portal:a-to-c",
            source_iri="urn:holon:a",
            target_iri="urn:holon:c",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
        )

    def test_remove_portal_returns_true_when_exists(self, ds):
        self._setup_two_portals(ds)
        result = ds.remove_portal("urn:portal:a-to-b")
        assert result is True

    def test_remove_portal_returns_false_when_missing(self, ds):
        """Idempotent: unknown portal IRI returns False, no error."""
        result = ds.remove_portal("urn:portal:does-not-exist")
        assert result is False

    def test_remove_portal_removes_only_that_portal(self, ds):
        """Sibling portal in the same boundary graph stays discoverable."""
        self._setup_two_portals(ds)
        ds.remove_portal("urn:portal:a-to-b")
        from_a = ds.find_portals_from("urn:holon:a")
        assert len(from_a) == 1
        assert from_a[0].iri == "urn:portal:a-to-c"

    def test_remove_portal_clears_incoming_discovery(self, ds):
        """find_portals_to no longer returns the removed portal."""
        self._setup_two_portals(ds)
        ds.remove_portal("urn:portal:a-to-b")
        assert ds.find_portals_to("urn:holon:b") == []
        # Unrelated target still has its portal
        to_c = ds.find_portals_to("urn:holon:c")
        assert len(to_c) == 1

    def test_remove_portal_preserves_boundary_graph(self, ds):
        """SHACL shapes in the shared boundary graph are untouched."""
        self._setup_two_portals(ds)
        ds.remove_portal("urn:portal:a-to-b")
        # SHACL shape still present
        shape_rows = list(ds.query(
            """
            PREFIX sh: <http://www.w3.org/ns/shacl#>
            SELECT ?s WHERE {
                GRAPH <urn:holon:a/boundary> {
                    ?s a sh:NodeShape .
                }
            }
            """
        ))
        assert len(shape_rows) == 1

    def test_remove_and_recreate_portal_is_clean(self, ds):
        """Removing then re-adding the same portal IRI produces clean state."""
        self._setup_two_portals(ds)
        ds.remove_portal("urn:portal:a-to-b")
        ds.add_portal(
            "urn:portal:a-to-b",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
        )
        from_a = ds.find_portals_from("urn:holon:a")
        assert len(from_a) == 2


# ══════════════════════════════════════════════════════════════
# Change 1 — remove_holon()
# ══════════════════════════════════════════════════════════════


class TestRemoveHolon:
    """Holon lifecycle: cascading cleanup of layers, portals, metadata."""

    def _setup_holarchy(self, ds):
        """Build a small holarchy for cleanup tests.

        Structure::

            root
            ├── child_a  (interior + boundary + context)
            └── child_b  (interior only)

            portal: child_a → child_b
            portal: child_b → child_a
        """
        ds.add_holon("urn:holon:root", "Root")
        ds.add_holon("urn:holon:child_a", "Child A", member_of="urn:holon:root")
        ds.add_holon("urn:holon:child_b", "Child B", member_of="urn:holon:root")

        ds.add_interior(
            "urn:holon:child_a",
            '<urn:x> a <urn:Thing> .',
        )
        ds.add_interior(
            "urn:holon:child_a",
            '<urn:y> a <urn:Thing> .',
            graph_iri="urn:holon:child_a/interior/fusion",
        )
        ds.add_boundary(
            "urn:holon:child_a",
            """
            @prefix sh: <http://www.w3.org/ns/shacl#> .
            <urn:shapes:S> a sh:NodeShape ;
                sh:targetClass <urn:Thing> .
            """,
        )
        ds.add_context("urn:holon:child_a", "<urn:e> <urn:p> <urn:o> .")

        ds.add_interior(
            "urn:holon:child_b",
            '<urn:z> a <urn:Thing> .',
        )

        ds.add_portal(
            "urn:portal:a-to-b",
            source_iri="urn:holon:child_a",
            target_iri="urn:holon:child_b",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
        )
        ds.add_portal(
            "urn:portal:b-to-a",
            source_iri="urn:holon:child_b",
            target_iri="urn:holon:child_a",
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { GRAPH ?g { ?s ?p ?o } }",
        )

    def test_remove_holon_returns_true_when_exists(self, ds):
        self._setup_holarchy(ds)
        assert ds.remove_holon("urn:holon:child_a") is True

    def test_remove_holon_returns_false_when_missing(self, ds):
        """Idempotent: unknown holon IRI returns False, no error."""
        assert ds.remove_holon("urn:holon:does-not-exist") is False

    def test_remove_holon_deletes_all_layer_graphs(self, ds):
        """All four layer graphs for the removed holon are deleted."""
        self._setup_holarchy(ds)
        layer_graphs = [
            "urn:holon:child_a/interior",
            "urn:holon:child_a/interior/fusion",
            "urn:holon:child_a/boundary",
            "urn:holon:child_a/context",
        ]
        # Confirm they exist first
        for g in layer_graphs:
            assert ds.backend.graph_exists(g), f"{g} should exist before removal"

        ds.remove_holon("urn:holon:child_a")

        for g in layer_graphs:
            assert not ds.backend.graph_exists(g), f"{g} should be gone after removal"

    def test_remove_holon_removes_from_list_holons(self, ds):
        self._setup_holarchy(ds)
        ds.remove_holon("urn:holon:child_a")
        iris = [h.iri for h in ds.list_holons()]
        assert "urn:holon:child_a" not in iris
        # Other holons intact
        assert "urn:holon:root" in iris
        assert "urn:holon:child_b" in iris

    def test_remove_holon_orphans_children_not_deletes_them(self, ds):
        """Removing a parent leaves children alive with no memberOf."""
        self._setup_holarchy(ds)
        ds.remove_holon("urn:holon:root")
        iris = [h.iri for h in ds.list_holons()]
        # Root is gone
        assert "urn:holon:root" not in iris
        # Children survive
        assert "urn:holon:child_a" in iris
        assert "urn:holon:child_b" in iris
        # Their memberOf triples are gone
        rows = list(ds.query(
            """
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?child WHERE {
                GRAPH <urn:holarchy:registry> {
                    ?child cga:memberOf <urn:holon:root> .
                }
            }
            """
        ))
        assert rows == []

    def test_remove_holon_cascades_portals_outgoing_and_incoming(self, ds):
        """All portals incident to the holon are removed."""
        self._setup_holarchy(ds)
        ds.remove_holon("urn:holon:child_a")
        # Outgoing portal gone
        assert ds.find_portals_from("urn:holon:child_a") == []
        # Incoming portal gone
        assert ds.find_portals_to("urn:holon:child_a") == []
        # The remaining holon has neither side
        assert ds.find_portals_from("urn:holon:child_b") == []
        assert ds.find_portals_to("urn:holon:child_b") == []

    def test_remove_holon_clears_registry_bindings(self, ds):
        """No hasInterior / hasBoundary / hasContext residue in the registry."""
        self._setup_holarchy(ds)
        ds.remove_holon("urn:holon:child_a")
        rows = list(ds.query(
            """
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?p ?o WHERE {
                GRAPH <urn:holarchy:registry> {
                    <urn:holon:child_a> ?p ?o .
                }
            }
            """
        ))
        assert rows == []

    def test_remove_and_recreate_holon_is_clean(self, ds):
        """Re-adding a holon with the same IRI starts fresh."""
        self._setup_holarchy(ds)
        ds.remove_holon("urn:holon:child_a")
        ds.add_holon("urn:holon:child_a", "Child A (reborn)")
        ds.add_interior("urn:holon:child_a", '<urn:new> a <urn:Thing> .')

        # list_holons sees it
        iris = [h.iri for h in ds.list_holons()]
        assert "urn:holon:child_a" in iris

        # Only the new triple is in the interior
        rows = list(ds.query(
            """
            SELECT ?s WHERE {
                GRAPH <urn:holon:child_a/interior> { ?s a <urn:Thing> }
            }
            """
        ))
        subjects = {str(r["s"]) for r in rows}
        assert subjects == {"urn:new"}


# ══════════════════════════════════════════════════════════════
# Eager metadata refresh behavior during cascade
# ══════════════════════════════════════════════════════════════


class TestRemoveHolonWithEagerMetadata:
    """Metadata invariants are preserved during cascading removal."""

    def test_eager_metadata_holds_after_remove(self):
        """After remove_holon with eager updates, registry metadata is consistent."""
        ds = HolonicDataset(RdflibBackend(), metadata_updates="eager")
        ds.add_holon("urn:holon:a", "A")
        ds.add_interior("urn:holon:a", '<urn:x> a <urn:T> .')
        ds.remove_holon("urn:holon:a")
        # Registry metadata should reflect the absence of the layer graph.
        # Query the registry for any metadata records referencing the
        # removed graph — there should be none.
        rows = list(ds.query(
            """
            PREFIX cga: <urn:holonic:ontology:>
            SELECT ?p ?o WHERE {
                GRAPH <urn:holarchy:registry> {
                    <urn:holon:a/interior> ?p ?o .
                }
            }
            """
        ))
        assert rows == []
