"""Tests for holonic.console_model dataclasses and serializers."""

from holonic.console_model import (
    ClassInstanceCount,
    HolonDetail,
    HolonSummary,
    NeighborhoodEdge,
    NeighborhoodGraph,
    NeighborhoodNode,
    PortalDetail,
    PortalSummary,
    _short,
)


class TestShortLabel:
    def test_urn_style(self):
        assert _short("urn:holon:foo") == "foo"

    def test_url_fragment(self):
        assert _short("http://example.org/ns#Bar") == "Bar"

    def test_url_path(self):
        assert _short("http://example.org/things/baz") == "baz"

    def test_empty(self):
        assert _short("") == ""

    def test_no_separators(self):
        assert _short("standalone") == "standalone"


class TestHolonSummary:
    def test_minimal(self):
        s = HolonSummary(iri="urn:holon:x")
        assert s.iri == "urn:holon:x"
        assert s.label is None
        assert s.kind is None
        assert s.health is None

    def test_full(self):
        s = HolonSummary(
            iri="urn:holon:x",
            label="X",
            kind="urn:holonic:ontology:DataHolon",
            classification="public",
            member_of="urn:holon:parent",
            interior_triple_count=42,
            health="intact",
        )
        assert s.kind == "urn:holonic:ontology:DataHolon"
        assert s.interior_triple_count == 42


class TestHolonDetail:
    def test_layer_lists_default_empty(self):
        d = HolonDetail(iri="urn:holon:x")
        assert d.interior_graphs == []
        assert d.boundary_graphs == []
        assert d.projection_graphs == []
        assert d.context_graphs == []


class TestClassInstanceCount:
    def test_count_int(self):
        c = ClassInstanceCount(class_iri="urn:cls:Foo", count=7)
        assert c.count == 7


class TestPortalDetail:
    def test_construct_query_optional(self):
        p = PortalDetail(
            iri="urn:portal:x",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
        )
        assert p.construct_query is None


class TestPortalSummary:
    def test_health_optional(self):
        p = PortalSummary(
            iri="urn:portal:x",
            source_iri="urn:holon:a",
            target_iri="urn:holon:b",
        )
        assert p.health is None
        assert p.last_traversal is None


class TestNeighborhoodGraphologyShape:
    """The `to_graphology()` output must match the contract documented
    in holonic-console's docs/GRAPH-COMPONENTS.md and consumable by
    sigma.js v3 via `graph.import(payload)`.
    """

    def test_empty_graph(self):
        g = NeighborhoodGraph(source_holon="urn:holon:foo", depth=1)
        out = g.to_graphology()
        assert out["attributes"]["sourceHolon"] == "urn:holon:foo"
        assert out["attributes"]["depth"] == 1
        assert out["attributes"]["name"] == "holon-neighborhood"
        assert out["nodes"] == []
        assert out["edges"] == []
        assert out["options"]["type"] == "directed"
        assert out["options"]["multi"] is True

    def test_node_attributes_complete(self):
        g = NeighborhoodGraph(
            source_holon="urn:holon:foo",
            depth=1,
            nodes=[
                NeighborhoodNode(
                    key="urn:holon:foo",
                    label="Foo",
                    kind="DataHolon",
                    health="intact",
                    triples=100,
                    size=14.0,
                )
            ],
        )
        node = g.to_graphology()["nodes"][0]
        assert node["key"] == "urn:holon:foo"
        attrs = node["attributes"]
        assert attrs["label"] == "Foo"
        assert attrs["nodeType"] == "holon"
        assert attrs["kind"] == "DataHolon"
        assert attrs["health"] == "intact"
        assert attrs["triples"] == 100
        assert attrs["size"] == 14.0

    def test_node_label_falls_back_to_iri_short(self):
        g = NeighborhoodGraph(
            source_holon="urn:holon:foo",
            depth=1,
            nodes=[NeighborhoodNode(key="urn:holon:bar")],
        )
        assert g.to_graphology()["nodes"][0]["attributes"]["label"] == "bar"

    def test_edge_attributes_complete(self):
        g = NeighborhoodGraph(
            source_holon="urn:holon:foo",
            depth=1,
            edges=[
                NeighborhoodEdge(
                    key="edge-0001",
                    source="urn:holon:foo",
                    target="urn:holon:bar",
                    edge_type="portal",
                    label="Foo→Bar",
                    health="intact",
                    size=2.0,
                )
            ],
        )
        edge = g.to_graphology()["edges"][0]
        assert edge["key"] == "edge-0001"
        assert edge["source"] == "urn:holon:foo"
        assert edge["target"] == "urn:holon:bar"
        attrs = edge["attributes"]
        assert attrs["edgeType"] == "portal"
        assert attrs["label"] == "Foo→Bar"
        assert attrs["health"] == "intact"
        assert attrs["size"] == 2.0
