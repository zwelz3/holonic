"""Tests for holon creation, discovery, and layer management."""

from holonic import HolonicDataset
from holonic.model import HolarchyTree


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


class TestDefaultConstructor:
    """HolonicDataset() with no arguments should work end-to-end."""

    def test_no_arg_constructor_uses_rdflib(self):
        ds = HolonicDataset()
        from holonic import RdflibBackend

        assert isinstance(ds.backend, RdflibBackend)

    def test_no_arg_constructor_is_functional(self):
        ds = HolonicDataset()
        ds.add_holon("urn:holon:x", "X")
        ds.add_interior("urn:holon:x", "<urn:a> <urn:b> <urn:c> .")
        info = ds.get_holon("urn:holon:x")
        assert info is not None
        assert len(info.interior_graphs) == 1

    def test_load_ontology_false_skips_cga_load(self):
        ds = HolonicDataset(load_ontology=False)
        # Registry graph should be empty / non-existent until something is added
        assert ds.list_holons() == []


class TestAllLayers:
    """add_projection and add_context were not previously covered."""

    def test_add_projection_creates_named_graph(self, ds):
        ds.add_holon("urn:holon:p", "P")
        graph_iri = ds.add_projection(
            "urn:holon:p",
            "<urn:n> <urn:p> <urn:o> .",
        )
        assert graph_iri == "urn:holon:p/projection"
        info = ds.get_holon("urn:holon:p")
        assert len(info.projection_graphs) == 1
        assert info.projection_graphs[0] == "urn:holon:p/projection"

    def test_add_context_creates_named_graph(self, ds):
        ds.add_holon("urn:holon:c", "C")
        graph_iri = ds.add_context(
            "urn:holon:c",
            "<urn:n> <urn:p> <urn:o> .",
        )
        assert graph_iri == "urn:holon:c/context"
        info = ds.get_holon("urn:holon:c")
        assert len(info.context_graphs) == 1

    def test_add_projection_with_explicit_graph_iri(self, ds):
        ds.add_holon("urn:holon:p", "P")
        graph_iri = ds.add_projection(
            "urn:holon:p",
            "<urn:n> <urn:p> <urn:o> .",
            graph_iri="urn:holon:p/projection/viz",
        )
        assert graph_iri == "urn:holon:p/projection/viz"
        info = ds.get_holon("urn:holon:p")
        assert "urn:holon:p/projection/viz" in info.projection_graphs

    def test_all_four_layers_on_one_holon(self, ds):
        ds.add_holon("urn:holon:full", "Full")
        ds.add_interior("urn:holon:full", "<urn:i> <urn:p> <urn:o> .")
        ds.add_boundary("urn:holon:full", "<urn:b> a sh:NodeShape .")
        ds.add_projection("urn:holon:full", "<urn:p> <urn:p> <urn:o> .")
        ds.add_context("urn:holon:full", "<urn:c> <urn:p> <urn:o> .")
        info = ds.get_holon("urn:holon:full")
        assert len(info.interior_graphs) == 1
        assert len(info.boundary_graphs) == 1
        assert len(info.projection_graphs) == 1
        assert len(info.context_graphs) == 1


class TestComputeDepthForest:
    """compute_depth on a forest of holarchies (multiple roots)."""

    def test_multiple_roots(self, ds):
        ds.add_holon("urn:holon:root-a", "Root A")
        ds.add_holon("urn:holon:root-b", "Root B")
        ds.add_holon("urn:holon:a-child", "A Child", member_of="urn:holon:root-a")
        ds.add_holon("urn:holon:b-child", "B Child", member_of="urn:holon:root-b")
        tree = ds.compute_depth()
        assert tree.get("urn:holon:root-a") == 0
        assert tree.get("urn:holon:root-b") == 0
        assert tree.get("urn:holon:a-child") == 1
        assert tree.get("urn:holon:b-child") == 1

    def test_deep_chain(self, ds):
        ds.add_holon("urn:holon:l0", "L0")
        for i in range(1, 6):
            ds.add_holon(
                f"urn:holon:l{i}",
                f"L{i}",
                member_of=f"urn:holon:l{i - 1}",
            )
        tree = ds.compute_depth()
        for i in range(6):
            assert tree.get(f"urn:holon:l{i}") == i

    def test_empty_dataset_returns_empty_tree(self, ds):
        tree = ds.compute_depth()
        assert len(tree) == 0
        assert tree.roots == []


class TestHolarchyTree:
    """HolarchyTree dict-like interface and rendering."""

    def _build(self, ds):
        ds.add_holon("urn:holon:org", "Acme")
        ds.add_holon("urn:holon:eng", "Engineering", member_of="urn:holon:org")
        ds.add_holon("urn:holon:ops", "Operations", member_of="urn:holon:org")
        ds.add_holon("urn:holon:eng-be", "Backend", member_of="urn:holon:eng")
        return ds.compute_depth()

    def test_returns_holarchy_tree_instance(self, ds):
        tree = self._build(ds)
        assert isinstance(tree, HolarchyTree)

    def test_dict_getitem(self, ds):
        tree = self._build(ds)
        assert tree["urn:holon:org"] == 0
        assert tree["urn:holon:eng-be"] == 2

    def test_contains(self, ds):
        tree = self._build(ds)
        assert "urn:holon:org" in tree
        assert "urn:holon:nonexistent" not in tree

    def test_len(self, ds):
        tree = self._build(ds)
        assert len(tree) == 4

    def test_iter(self, ds):
        tree = self._build(ds)
        iris = set(iter(tree))
        assert "urn:holon:org" in iris
        assert "urn:holon:eng-be" in iris

    def test_items(self, ds):
        tree = self._build(ds)
        d = dict(tree.items())
        assert d["urn:holon:org"] == 0

    def test_get_with_default(self, ds):
        tree = self._build(ds)
        assert tree.get("urn:holon:missing", -1) == -1

    def test_roots_property(self, ds):
        tree = self._build(ds)
        assert tree.roots == ["urn:holon:org"]

    def test_roots_multiple(self, ds):
        ds.add_holon("urn:holon:r1", "R1")
        ds.add_holon("urn:holon:r2", "R2")
        ds.add_holon("urn:holon:c", "C", member_of="urn:holon:r1")
        tree = ds.compute_depth()
        assert set(tree.roots) == {"urn:holon:r1", "urn:holon:r2"}

    def test_str_renders_tree(self, ds):
        tree = self._build(ds)
        s = str(tree)
        # Root labeled, children indented under it
        assert "Acme" in s
        assert "Engineering" in s
        assert "Backend" in s
        # Child connector somewhere in output
        assert "└──" in s or "├──" in s

    def test_repr_includes_counts(self, ds):
        tree = self._build(ds)
        r = repr(tree)
        assert "4 holons" in r
        assert "1 roots" in r

    def test_parents_and_children_maps(self, ds):
        tree = self._build(ds)
        assert tree.parents["urn:holon:eng-be"] == "urn:holon:eng"
        assert "urn:holon:eng-be" in tree.children["urn:holon:eng"]
        # Root has no parent entry
        assert "urn:holon:org" not in tree.parents
