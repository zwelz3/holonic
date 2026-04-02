"""Tests for holon creation, discovery, and layer management."""


class TestHolonCreation:
    def test_add_holon_registers_in_registry(self, ds):
        ds.add_holon("urn:holon:test", "Test Holon")
        holons = ds.list_holons()
        assert len(holons) == 1
        assert holons[0].iri == "urn:holon:test"
        assert holons[0].label == "Test Holon"

    def test_add_multiple_holons(self, ds):
        ds.add_holon("urn:holon:a", "Holon A")
        ds.add_holon("urn:holon:b", "Holon B")
        ds.add_holon("urn:holon:c", "Holon C")
        holons = ds.list_holons()
        assert len(holons) == 3
        iris = {h.iri for h in holons}
        assert iris == {"urn:holon:a", "urn:holon:b", "urn:holon:c"}

    def test_add_holon_with_membership(self, ds):
        ds.add_holon("urn:holon:parent", "Parent")
        ds.add_holon("urn:holon:child", "Child", member_of="urn:holon:parent")
        holons = ds.list_holons()
        assert len(holons) == 2

    def test_get_holon_returns_none_for_missing(self, ds):
        assert ds.get_holon("urn:holon:nonexistent") is None

    def test_get_holon_returns_info(self, ds):
        ds.add_holon("urn:holon:test", "Test")
        info = ds.get_holon("urn:holon:test")
        assert info is not None
        assert info.iri == "urn:holon:test"


class TestComputeDepth:
    def test_root_has_depth_zero(self, ds):
        ds.add_holon("urn:holon:root", "Root")
        depths = ds.compute_depth()
        assert depths.get("urn:holon:root") == 0

    def test_child_has_depth_one(self, ds):
        ds.add_holon("urn:holon:root", "Root")
        ds.add_holon("urn:holon:child", "Child", member_of="urn:holon:root")
        depths = ds.compute_depth()
        assert depths.get("urn:holon:root") == 0
        assert depths.get("urn:holon:child") == 1

    def test_nested_depth(self, ds):
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B", member_of="urn:holon:a")
        ds.add_holon("urn:holon:c", "C", member_of="urn:holon:b")
        depths = ds.compute_depth()
        assert depths.get("urn:holon:a") == 0
        assert depths.get("urn:holon:b") == 1
        assert depths.get("urn:holon:c") == 2

    def test_single_holon_depth(self, ds):
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B", member_of="urn:holon:a")
        depths = ds.compute_depth("urn:holon:b")
        assert depths.get("urn:holon:b") == 1


class TestLayers:
    def test_add_interior_creates_named_graph(self, ds):
        ds.add_holon("urn:holon:test", "Test")
        ds.add_interior(
            "urn:holon:test",
            """
            <urn:thing:1> a <urn:type:Thing> .
        """,
        )
        info = ds.get_holon("urn:holon:test")
        assert len(info.interior_graphs) == 1
        assert info.interior_graphs[0] == "urn:holon:test/interior"

    def test_multiple_interiors(self, ds):
        ds.add_holon("urn:holon:fused", "Fused")
        ds.add_interior(
            "urn:holon:fused",
            """
            <urn:a> a <urn:type:A> .
        """,
            graph_iri="urn:holon:fused/interior/radar",
        )
        ds.add_interior(
            "urn:holon:fused",
            """
            <urn:b> a <urn:type:B> .
        """,
            graph_iri="urn:holon:fused/interior/eo-ir",
        )

        info = ds.get_holon("urn:holon:fused")
        assert len(info.interior_graphs) == 2

    def test_add_boundary(self, ds):
        ds.add_holon("urn:holon:test", "Test")
        ds.add_boundary(
            "urn:holon:test",
            """
            <urn:shape:S> a sh:NodeShape .
        """,
        )
        info = ds.get_holon("urn:holon:test")
        assert len(info.boundary_graphs) == 1

    def test_layer_data_is_queryable(self, ds):
        ds.add_holon("urn:holon:test", "Test")
        ds.add_interior(
            "urn:holon:test",
            """
            @prefix ex: <urn:ex:> .
            <urn:entity:1> a ex:Widget ;
                ex:weight 42 .
        """,
        )
        rows = ds.query("""
            PREFIX ex: <urn:ex:>
            SELECT ?s ?w WHERE {
                GRAPH <urn:holon:test/interior> {
                    ?s a ex:Widget ; ex:weight ?w .
                }
            }
        """)
        assert len(rows) == 1
        assert rows[0]["w"] == 42


class TestSummary:
    def test_summary_includes_holons(self, ds_with_holons):
        s = ds_with_holons.summary()
        assert "Source Holon" in s
        assert "Target Holon" in s

    def test_summary_includes_portals(self, ds_with_holons):
        s = ds_with_holons.summary()
        assert "Portal" in s or "→" in s
