"""Tests for portal discovery, traversal, and path finding."""

import pytest
from holonic import HolonicDataset, RdflibBackend


class TestPortalDiscovery:
    def test_find_portals_from(self, ds_with_holons):
        portals = ds_with_holons.find_portals_from("urn:holon:source")
        assert len(portals) >= 1
        p = portals[0]
        assert p.source_iri == "urn:holon:source"
        assert p.target_iri == "urn:holon:target"

    def test_find_portals_to(self, ds_with_holons):
        portals = ds_with_holons.find_portals_to("urn:holon:target")
        assert len(portals) >= 1
        assert portals[0].target_iri == "urn:holon:target"

    def test_find_portal_direct(self, ds_with_holons):
        p = ds_with_holons.find_portal("urn:holon:source", "urn:holon:target")
        assert p is not None
        assert p.iri == "urn:portal:src-to-tgt"

    def test_find_portal_returns_none_for_missing(self, ds_with_holons):
        p = ds_with_holons.find_portal("urn:holon:target", "urn:holon:source")
        assert p is None

    def test_find_portals_from_empty(self, ds):
        ds.add_holon("urn:holon:lonely", "Lonely")
        portals = ds.find_portals_from("urn:holon:lonely")
        assert portals == []


class TestPortalTraversal:
    def test_traverse_portal_produces_triples(self, ds_with_holons):
        projected = ds_with_holons.traverse_portal("urn:portal:src-to-tgt")
        assert len(projected) > 0

    def test_traverse_portal_injects_into_target(self, ds_with_holons):
        ds_with_holons.traverse_portal(
            "urn:portal:src-to-tgt",
            inject_into="urn:holon:target/interior",
        )
        g = ds_with_holons.backend.get_graph("urn:holon:target/interior")
        assert len(g) > 0

    def test_traverse_shorthand(self, ds_with_holons):
        projected, result = ds_with_holons.traverse(
            "urn:holon:source",
            "urn:holon:target",
            validate=False,
        )
        assert len(projected) > 0

    def test_traverse_raises_on_missing_portal(self, ds_with_holons):
        with pytest.raises(ValueError, match="No direct portal"):
            ds_with_holons.traverse(
                "urn:holon:target", "urn:holon:source"
            )

    def test_traverse_portal_raises_on_unknown_portal(self, ds):
        with pytest.raises(ValueError, match="not found"):
            ds.traverse_portal("urn:portal:nonexistent")


class TestPathFinding:
    def test_direct_path(self, ds_with_holons):
        path = ds_with_holons.find_path("urn:holon:source", "urn:holon:target")
        assert path is not None
        assert len(path) == 1
        assert path[0].source_iri == "urn:holon:source"
        assert path[0].target_iri == "urn:holon:target"

    def test_no_path_returns_none(self, ds_with_holons):
        path = ds_with_holons.find_path("urn:holon:target", "urn:holon:source")
        assert path is None

    def test_multi_hop_path(self, ds):
        ds.add_holon("urn:holon:a", "A")
        ds.add_holon("urn:holon:b", "B")
        ds.add_holon("urn:holon:c", "C")
        ds.add_interior("urn:holon:a", "<urn:x> a <urn:T> .")
        ds.add_interior("urn:holon:b", "")
        ds.add_interior("urn:holon:c", "")

        # A → B → C (no direct A → C)
        ds.add_portal("urn:portal:a-to-b", "urn:holon:a", "urn:holon:b",
                      "CONSTRUCT { ?s a <urn:T> } WHERE { ?s a <urn:T> }",
                      label="A→B")
        ds.add_portal("urn:portal:b-to-c", "urn:holon:b", "urn:holon:c",
                      "CONSTRUCT { ?s a <urn:T> } WHERE { ?s a <urn:T> }",
                      label="B→C")

        path = ds.find_path("urn:holon:a", "urn:holon:c")
        assert path is not None
        assert len(path) == 2
        assert path[0].source_iri == "urn:holon:a"
        assert path[1].target_iri == "urn:holon:c"
