"""Tests for GraphBackend protocol and rdflib implementation."""

import pytest
from rdflib import Graph, URIRef

from holonic.backends import GraphBackend, RdflibBackend


class TestProtocolConformance:
    def test_rdflib_backend_implements_protocol(self):
        backend = RdflibBackend()
        assert isinstance(backend, GraphBackend)


class TestRdflibBackend:
    @pytest.fixture
    def backend(self):
        return RdflibBackend()

    def test_parse_and_retrieve(self, backend):
        backend.parse_into(
            "urn:g:1",
            """
            <urn:s> <urn:p> "hello" .
        """,
            "turtle",
        )
        g = backend.get_graph("urn:g:1")
        assert len(g) == 1

    def test_graph_exists(self, backend):
        assert not backend.graph_exists("urn:g:empty")
        backend.parse_into("urn:g:full", "<urn:a> <urn:b> <urn:c> .")
        assert backend.graph_exists("urn:g:full")

    def test_put_replaces(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        g2 = Graph()
        g2.add((URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")))
        backend.put_graph("urn:g:1", g2)
        g = backend.get_graph("urn:g:1")
        assert (URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")) in g
        assert (URIRef("urn:a"), URIRef("urn:b"), URIRef("urn:c")) not in g

    def test_post_appends(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        g2 = Graph()
        g2.add((URIRef("urn:x"), URIRef("urn:y"), URIRef("urn:z")))
        backend.post_graph("urn:g:1", g2)
        g = backend.get_graph("urn:g:1")
        assert len(g) == 2

    def test_delete_graph(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        backend.delete_graph("urn:g:1")
        assert not backend.graph_exists("urn:g:1")

    def test_query_select(self, backend):
        backend.parse_into(
            "urn:g:1",
            """
            @prefix ex: <urn:ex:> .
            ex:a ex:val 42 .
            ex:b ex:val 99 .
        """,
        )
        rows = backend.query("""
            SELECT ?s ?v WHERE {
                GRAPH <urn:g:1> { ?s <urn:ex:val> ?v }
            }
            ORDER BY ?v
        """)
        assert len(rows) == 2
        assert rows[0]["v"] == 42
        assert rows[1]["v"] == 99

    def test_construct(self, backend):
        backend.parse_into(
            "urn:g:1",
            """
            <urn:s> a <urn:T> ; <urn:name> "test" .
        """,
        )
        g = backend.construct("""
            CONSTRUCT { ?s <urn:label> ?n }
            WHERE {
                GRAPH <urn:g:1> { ?s <urn:name> ?n }
            }
        """)
        assert len(g) == 1

    def test_ask(self, backend):
        backend.parse_into("urn:g:1", "<urn:a> <urn:b> <urn:c> .")
        assert backend.ask("ASK { GRAPH <urn:g:1> { <urn:a> <urn:b> <urn:c> } }")
        assert not backend.ask("ASK { GRAPH <urn:g:1> { <urn:x> <urn:y> <urn:z> } }")

    def test_list_named_graphs(self, backend):
        backend.parse_into("urn:g:alpha", "<urn:a> <urn:b> <urn:c> .")
        backend.parse_into("urn:g:beta", "<urn:x> <urn:y> <urn:z> .")
        graphs = backend.list_named_graphs()
        assert "urn:g:alpha" in graphs
        assert "urn:g:beta" in graphs

    def test_update(self, backend):
        backend.update("""
            INSERT DATA {
                GRAPH <urn:g:new> { <urn:a> <urn:b> "inserted" }
            }
        """)
        assert backend.graph_exists("urn:g:new")
        rows = backend.query("""
            SELECT ?o WHERE {
                GRAPH <urn:g:new> { <urn:a> <urn:b> ?o }
            }
        """)
        assert len(rows) == 1


class TestRdflibBackendBindings:
    """The **bindings kwarg auto-coerces urn: strings to URIRef."""

    @pytest.fixture
    def backend(self):
        b = RdflibBackend()
        b.parse_into(
            "urn:g:bind",
            """
            @prefix ex: <urn:ex:> .
            ex:alice ex:knows ex:bob .
            ex:bob ex:knows ex:carol .
        """,
        )
        return b

    def test_query_with_urn_binding_coerces_to_uriref(self, backend):
        rows = backend.query(
            """
            SELECT ?o WHERE {
                GRAPH <urn:g:bind> { ?s <urn:ex:knows> ?o }
            }
            """,
            s="urn:ex:alice",
        )
        assert len(rows) == 1
        assert rows[0]["o"] == "urn:ex:bob"

    def test_construct_with_binding(self, backend):
        g = backend.construct(
            """
            CONSTRUCT { ?s <urn:label> "found" }
            WHERE {
                GRAPH <urn:g:bind> { ?s <urn:ex:knows> ?o }
            }
            """,
            s="urn:ex:alice",
        )
        assert len(g) == 1

    def test_ask_with_binding(self, backend):
        assert backend.ask(
            """
            ASK { GRAPH <urn:g:bind> { ?s <urn:ex:knows> <urn:ex:bob> } }
            """,
            s="urn:ex:alice",
        )
        assert not backend.ask(
            """
            ASK { GRAPH <urn:g:bind> { ?s <urn:ex:knows> <urn:ex:bob> } }
            """,
            s="urn:ex:carol",
        )


class TestRdflibBackendDatasetAccess:
    """The .dataset property exposes the underlying rdflib.Dataset."""

    def test_dataset_property_is_rdflib_dataset(self):
        from rdflib import Dataset

        b = RdflibBackend()
        assert isinstance(b.dataset, Dataset)

    def test_constructor_accepts_existing_dataset(self):
        from rdflib import Dataset

        ds = Dataset()
        ds.graph(URIRef("urn:g:pre")).add((URIRef("urn:a"), URIRef("urn:b"), URIRef("urn:c")))
        b = RdflibBackend(dataset=ds)
        assert b.graph_exists("urn:g:pre")
        assert b.dataset is ds
