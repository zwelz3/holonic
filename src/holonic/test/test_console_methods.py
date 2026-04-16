"""Tests for the 0.3.1 console-facing HolonicDataset methods.

These cover list_holons_summary, get_holon_detail, holon_interior_classes,
holon_neighborhood, list_portals, get_portal, and portal_traversal_history.
All run against the in-memory RdflibBackend; no network required.
"""

import pytest

from holonic import HolonicDataset, RdflibBackend
from holonic.console_model import (
    ClassInstanceCount,
    HolonDetail,
    HolonSummary,
    NeighborhoodGraph,
    PortalDetail,
    PortalSummary,
)


@pytest.fixture
def populated_ds():
    """A small holarchy: parent + two children, two portals between them."""
    ds = HolonicDataset(RdflibBackend())
    ds.add_holon("urn:holon:parent", "Parent")
    ds.add_holon("urn:holon:alpha", "Alpha", member_of="urn:holon:parent")
    ds.add_holon("urn:holon:beta", "Beta", member_of="urn:holon:parent")
    ds.add_interior(
        "urn:holon:alpha",
        """
        @prefix ex: <urn:ex:> .
        <urn:item:1> a ex:Widget ; ex:name "one" .
        <urn:item:2> a ex:Widget ; ex:name "two" .
        <urn:item:3> a ex:Gadget ; ex:name "three" .
        """,
    )
    ds.add_interior(
        "urn:holon:beta",
        """
        @prefix ex: <urn:ex:> .
        <urn:item:9> a ex:Widget ; ex:name "nine" .
        """,
    )
    construct = """
        PREFIX ex: <urn:ex:>
        CONSTRUCT { ?s a ex:Widget } WHERE { ?s a ex:Widget }
    """
    ds.add_portal(
        "urn:portal:alpha-to-beta",
        "urn:holon:alpha",
        "urn:holon:beta",
        construct,
        label="Alpha → Beta",
    )
    ds.add_portal(
        "urn:portal:beta-to-alpha",
        "urn:holon:beta",
        "urn:holon:alpha",
        construct,
        label="Beta → Alpha",
    )
    return ds


# ══════════════════════════════════════════════════════════════
# list_holons_summary
# ══════════════════════════════════════════════════════════════


class TestListHolonsSummary:
    def test_empty_dataset(self):
        ds = HolonicDataset(RdflibBackend())
        assert ds.list_holons_summary() == []

    def test_returns_summaries(self, populated_ds):
        out = populated_ds.list_holons_summary()
        assert len(out) == 3
        assert all(isinstance(s, HolonSummary) for s in out)
        iris = {s.iri for s in out}
        assert iris == {
            "urn:holon:parent",
            "urn:holon:alpha",
            "urn:holon:beta",
        }

    def test_member_of_populated(self, populated_ds):
        by_iri = {s.iri: s for s in populated_ds.list_holons_summary()}
        assert by_iri["urn:holon:alpha"].member_of == "urn:holon:parent"
        assert by_iri["urn:holon:beta"].member_of == "urn:holon:parent"
        assert by_iri["urn:holon:parent"].member_of is None

    def test_labels_populated(self, populated_ds):
        by_iri = {s.iri: s for s in populated_ds.list_holons_summary()}
        assert by_iri["urn:holon:alpha"].label == "Alpha"


# ══════════════════════════════════════════════════════════════
# get_holon_detail
# ══════════════════════════════════════════════════════════════


class TestGetHolonDetail:
    def test_missing_returns_none(self, populated_ds):
        assert populated_ds.get_holon_detail("urn:holon:nope") is None

    def test_returns_layer_iris(self, populated_ds):
        d = populated_ds.get_holon_detail("urn:holon:alpha")
        assert isinstance(d, HolonDetail)
        assert d.iri == "urn:holon:alpha"
        assert d.label == "Alpha"
        assert d.member_of == "urn:holon:parent"
        assert "urn:holon:alpha/interior" in d.interior_graphs

    def test_interior_triple_count_present(self, populated_ds):
        # alpha has 6 triples (2 widgets x 2 + 1 gadget x 2 = 6)
        d = populated_ds.get_holon_detail("urn:holon:alpha")
        assert d.interior_triple_count is not None
        assert d.interior_triple_count >= 6


# ══════════════════════════════════════════════════════════════
# holon_interior_classes
# ══════════════════════════════════════════════════════════════


class TestHolonInteriorClasses:
    def test_empty_for_no_interior(self):
        ds = HolonicDataset(RdflibBackend())
        ds.add_holon("urn:holon:bare", "Bare")
        assert ds.holon_interior_classes("urn:holon:bare") == []

    def test_counts_distinct_subjects_per_class(self, populated_ds):
        out = populated_ds.holon_interior_classes("urn:holon:alpha")
        assert all(isinstance(c, ClassInstanceCount) for c in out)
        by_class = {c.class_iri: c.count for c in out}
        assert by_class.get("urn:ex:Widget") == 2
        assert by_class.get("urn:ex:Gadget") == 1

    def test_unknown_holon_returns_empty(self, populated_ds):
        assert populated_ds.holon_interior_classes("urn:holon:nope") == []


# ══════════════════════════════════════════════════════════════
# holon_neighborhood
# ══════════════════════════════════════════════════════════════


class TestHolonNeighborhood:
    def test_returns_graphology_compatible(self, populated_ds):
        n = populated_ds.holon_neighborhood("urn:holon:alpha", depth=1)
        assert isinstance(n, NeighborhoodGraph)
        payload = n.to_graphology()
        assert "nodes" in payload
        assert "edges" in payload

    def test_depth_zero_only_source(self, populated_ds):
        n = populated_ds.holon_neighborhood("urn:holon:alpha", depth=0)
        assert n.source_holon == "urn:holon:alpha"
        assert len(n.nodes) == 1
        assert n.nodes[0].key == "urn:holon:alpha"
        assert n.edges == []

    def test_depth_one_includes_portal_neighbors(self, populated_ds):
        n = populated_ds.holon_neighborhood("urn:holon:alpha", depth=1)
        keys = {node.key for node in n.nodes}
        assert "urn:holon:alpha" in keys
        assert "urn:holon:beta" in keys
        # Both portals connect alpha↔beta, so both edges should appear
        assert len(n.edges) == 2

    def test_negative_depth_rejected(self, populated_ds):
        with pytest.raises(ValueError):
            populated_ds.holon_neighborhood("urn:holon:alpha", depth=-1)

    def test_unknown_holon_returns_singleton(self, populated_ds):
        # Dangling-reference behavior: the source still appears as a
        # node so the operator sees the question they asked.
        n = populated_ds.holon_neighborhood("urn:holon:ghost", depth=1)
        assert len(n.nodes) == 1
        assert n.nodes[0].key == "urn:holon:ghost"
        assert n.edges == []

    def test_edge_keys_deterministic(self, populated_ds):
        n1 = populated_ds.holon_neighborhood("urn:holon:alpha", depth=1)
        n2 = populated_ds.holon_neighborhood("urn:holon:alpha", depth=1)
        keys1 = sorted(e.key for e in n1.edges)
        keys2 = sorted(e.key for e in n2.edges)
        assert keys1 == keys2

    def test_node_attributes_carry_through_to_payload(self, populated_ds):
        payload = populated_ds.holon_neighborhood("urn:holon:alpha", depth=1).to_graphology()
        for node in payload["nodes"]:
            attrs = node["attributes"]
            assert "label" in attrs
            assert attrs["nodeType"] == "holon"
            assert "size" in attrs


# ══════════════════════════════════════════════════════════════
# list_portals / get_portal
# ══════════════════════════════════════════════════════════════


class TestListPortals:
    def test_empty(self):
        ds = HolonicDataset(RdflibBackend())
        assert ds.list_portals() == []

    def test_returns_summaries(self, populated_ds):
        out = populated_ds.list_portals()
        assert len(out) == 2
        assert all(isinstance(p, PortalSummary) for p in out)
        iris = {p.iri for p in out}
        assert iris == {"urn:portal:alpha-to-beta", "urn:portal:beta-to-alpha"}


class TestGetPortal:
    def test_missing_returns_none(self, populated_ds):
        assert populated_ds.get_portal("urn:portal:nope") is None

    def test_returns_construct_query(self, populated_ds):
        p = populated_ds.get_portal("urn:portal:alpha-to-beta")
        assert isinstance(p, PortalDetail)
        assert p.source_iri == "urn:holon:alpha"
        assert p.target_iri == "urn:holon:beta"
        assert p.construct_query is not None
        assert "CONSTRUCT" in p.construct_query


# ══════════════════════════════════════════════════════════════
# portal_traversal_history
# ══════════════════════════════════════════════════════════════


class TestPortalTraversalHistory:
    def test_unknown_portal_returns_empty(self, populated_ds):
        assert populated_ds.portal_traversal_history("urn:portal:nope") == []

    def test_no_history_returns_empty(self, populated_ds):
        # No traversals recorded yet
        assert populated_ds.portal_traversal_history("urn:portal:alpha-to-beta") == []

    def test_records_appear(self, populated_ds):
        # Manually record a couple of traversals
        populated_ds.record_traversal(
            portal_iri="urn:portal:alpha-to-beta",
            source_iri="urn:holon:alpha",
            target_iri="urn:holon:beta",
            agent_iri="urn:agent:test",
        )
        populated_ds.record_traversal(
            portal_iri="urn:portal:alpha-to-beta",
            source_iri="urn:holon:alpha",
            target_iri="urn:holon:beta",
            agent_iri="urn:agent:test",
        )
        records = populated_ds.portal_traversal_history("urn:portal:alpha-to-beta")
        assert len(records) == 2
        assert all(r.source_iri == "urn:holon:alpha" for r in records)
        assert all(r.target_iri == "urn:holon:beta" for r in records)

    def test_limit_clamped(self, populated_ds):
        # limit=0 must not raise; gets clamped to 1
        out = populated_ds.portal_traversal_history("urn:portal:alpha-to-beta", limit=0)
        assert isinstance(out, list)


# ══════════════════════════════════════════════════════════════
# FusekiBackend.extra_headers wiring
# ══════════════════════════════════════════════════════════════


class TestFusekiBackendExtraHeaders:
    def test_extra_headers_forwarded_to_client_kwargs(self):
        # We can't open a real session in a unit test, but we can assert
        # that FusekiBackend stores extra_headers in the kwargs passed
        # to FusekiClient.
        pytest.importorskip("aiohttp")
        from holonic.backends.fuseki_backend import FusekiBackend

        backend = FusekiBackend(
            "http://fuseki.test:3030",
            "ds",
            extra_headers={"Authorization": "Bearer abc"},
        )
        assert backend._client_kwargs.get("extra_headers") == {"Authorization": "Bearer abc"}

    def test_no_extra_headers_omits_kwarg(self):
        pytest.importorskip("aiohttp")
        from holonic.backends.fuseki_backend import FusekiBackend

        backend = FusekiBackend("http://fuseki.test:3030", "ds")
        assert "extra_headers" not in backend._client_kwargs

    def test_fuseki_client_stores_extra_headers(self):
        pytest.importorskip("aiohttp")
        from holonic.backends._fuseki_client import FusekiClient

        client = FusekiClient(
            "http://fuseki.test:3030",
            "ds",
            extra_headers={"X-Tenant": "acme"},
        )
        assert client.extra_headers == {"X-Tenant": "acme"}

    def test_fuseki_client_extra_headers_default_empty(self):
        pytest.importorskip("aiohttp")
        from holonic.backends._fuseki_client import FusekiClient

        client = FusekiClient("http://fuseki.test:3030", "ds")
        assert client.extra_headers == {}
